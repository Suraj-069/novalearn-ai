"""Processing-job runner: inspect -> extract -> chunk -> embed -> index -> topics.

Runs in a FastAPI background task with its own DB session. Failures are recorded on the job
with a user-presentable message; unexpected errors are logged server-side only.
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import SessionLocal
from app.models._types import utcnow
from app.models.course import Document, ProcessingJob
from app.services.ingestion.extract import ExtractionError
from app.services.ingestion.inspect import InspectionError, inspect_file
from app.services.ingestion.pipeline import index_document
from app.services.providers.base import ProviderError

log = logging.getLogger("novalearn.ingestion")


def create_job(db: Session, document: Document) -> ProcessingJob:
    job = ProcessingJob(document_id=document.id, status="queued", stage="queued")
    db.add(job)
    db.flush()
    return job


def run_job(job_id) -> None:
    db = SessionLocal()
    try:
        job = db.get(ProcessingJob, job_id)
        doc = db.get(Document, job.document_id) if job else None
        if job is None or doc is None:
            return
        job.status, job.stage = "processing", "inspecting"
        job.attempts += 1
        job.started_at, job.finished_at, job.error = utcnow(), None, None
        db.commit()

        try:
            path = get_settings().upload_root / doc.stored_path
            if not path.is_file():
                raise InspectionError("The stored file is missing from disk. Upload it again.")
            result = inspect_file(doc.source_type, path)
            doc.page_count, doc.slide_count = result.page_count, result.slide_count
            doc.duration_seconds, doc.has_text_layer = result.duration_seconds, result.has_text_layer
            doc.file_meta = result.meta
            job.status, job.stage = "processing", "inspected"
            db.commit()

            index_document(db, job, doc, path)
            job.status, job.stage = "indexed", "indexed"
        except (InspectionError, ExtractionError, ProviderError) as e:
            db.rollback()
            job = db.get(ProcessingJob, job_id)
            job.status, job.error = "failed", str(e)
        except Exception:
            db.rollback()
            log.exception("Unexpected failure processing document %s", job_id)
            job = db.get(ProcessingJob, job_id)
            job.status = "failed"
            job.error = "Something went wrong while processing this file. Try again, or upload a different copy."
        job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()
