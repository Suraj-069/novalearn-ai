import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course, owned_document
from app.core.config import get_settings
from app.database.session import get_db
from app.models.course import Document
from app.models.user import User
from app.schemas.course import DocumentOut, JobOut
from app.services.ingestion.runner import create_job, run_job
from app.services.ingestion.validation import save_validated_upload

router = APIRouter(prefix="/api", tags=["documents"])


def _doc_out(doc: Document) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.job = JobOut.model_validate(doc.jobs[0]) if doc.jobs else None
    return out


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut])
def list_documents(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    docs = db.scalars(select(Document).where(Document.course_id == course_id).order_by(Document.created_at.desc())).all()
    return [_doc_out(d) for d in docs]


@router.post("/courses/{course_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    course_id: uuid.UUID,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    course = owned_course(course_id, user, db)
    doc_id = uuid.uuid4()
    saved = await save_validated_upload(file, str(course.id), str(doc_id))
    doc = Document(
        id=doc_id, course_id=course.id, original_filename=saved.display_name, stored_path=saved.rel_path,
        source_type=saved.kind.source_type, mime_type=saved.kind.mime, size_bytes=saved.size, sha256=saved.sha256,
    )
    db.add(doc)
    db.flush()
    job = create_job(db, doc)
    db.commit()
    db.refresh(doc)
    background.add_task(run_job, job.id)
    return _doc_out(doc)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _doc_out(owned_document(document_id, user, db))


@router.get("/documents/{document_id}/file")
def download_document(document_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Authorised access to the original file. Stage 3 builds page/slide/timestamp openers on top."""
    doc = owned_document(document_id, user, db)
    path = get_settings().upload_root / doc.stored_path
    if not path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="The stored file is missing.")
    return FileResponse(path, media_type=doc.mime_type, filename=doc.original_filename, content_disposition_type="inline")


@router.post("/documents/{document_id}/retry", response_model=DocumentOut)
def retry_document(document_id: uuid.UUID, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(document_id, user, db)
    latest = doc.jobs[0] if doc.jobs else None
    if latest is not None and latest.status == "processing":
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="This file is already being processed.")
    job = create_job(db, doc)
    db.commit()
    db.refresh(doc)
    background.add_task(run_job, job.id)
    return _doc_out(doc)


@router.post("/documents/{document_id}/replace", response_model=DocumentOut)
async def replace_document(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Swap the file behind an existing document and re-run processing."""
    doc = owned_document(document_id, user, db)
    old_path = get_settings().upload_root / doc.stored_path
    new_id = uuid.uuid4()
    saved = await save_validated_upload(file, str(doc.course_id), str(new_id))
    doc.original_filename, doc.stored_path = saved.display_name, saved.rel_path
    doc.source_type, doc.mime_type = saved.kind.source_type, saved.kind.mime
    doc.size_bytes, doc.sha256 = saved.size, saved.sha256
    doc.page_count = doc.slide_count = doc.duration_seconds = doc.has_text_layer = None
    doc.file_meta = {}
    job = create_job(db, doc)
    db.commit()
    db.refresh(doc)
    old_path.unlink(missing_ok=True)
    background.add_task(run_job, job.id)
    return _doc_out(doc)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(document_id, user, db)
    path = get_settings().upload_root / doc.stored_path
    db.delete(doc)
    db.commit()
    path.unlink(missing_ok=True)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from fastapi import HTTPException

    from app.models.course import ProcessingJob
    job = db.get(ProcessingJob, job_id)
    if job is None or job.document.course.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job
