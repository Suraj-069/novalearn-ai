"""Indexing pipeline: extract -> chunk -> embed -> store -> verify -> topics."""
import logging
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.course import Document, ProcessingJob
from app.models.knowledge import ContentChunk
from app.services.ingestion import extract as ex
from app.services.ingestion.chunking import chunk_units
from app.services.knowledge.topics import after_indexing
from app.services.providers.base import ProviderUnavailable
from app.services.providers.embeddings import get_embedding_provider
from app.services.providers.llm import get_llm
from app.services.providers.stt import get_stt

log = logging.getLogger("novalearn.pipeline")
EMBED_BATCH = 64


def _stage(db: Session, job: ProcessingJob, stage: str) -> None:
    job.stage = stage
    db.commit()  # committed so the UI's status polling sees live progress


def _optional_llm():
    try:
        return get_llm()
    except ProviderUnavailable as e:
        log.warning("LLM unavailable, continuing without it: %s", e)
        return None


def _extract(doc: Document, path: Path, llm) -> ex.Extraction:
    t = doc.source_type
    if t == "pdf":
        return ex.extract_pdf(path, llm)
    if t == "pptx":
        return ex.extract_pptx(path, llm)
    if t == "image":
        return ex.extract_image(path, llm, label=doc.original_filename)
    if t == "transcript":
        return ex.extract_transcript(path)
    if t == "video":
        return ex.extract_video(path, get_stt())
    raise ex.ExtractionError(f"Unsupported source type '{t}'.")


def index_document(db: Session, job: ProcessingJob, doc: Document, path: Path) -> None:
    """Raises ExtractionError / ProviderError for user-presentable failures."""
    llm = _optional_llm()
    embedder = get_embedding_provider()

    _stage(db, job, "extracting")
    extraction = _extract(doc, path, llm)
    if not extraction.units:
        hint = " Install Tesseract so scanned pages can be read." if doc.source_type in ("pdf", "pptx", "image") and doc.file_meta.get("needs_ocr") else ""
        raise ex.ExtractionError("No readable text was found in this file." + hint)

    _stage(db, job, "chunking")
    chunks = chunk_units(extraction.units)

    _stage(db, job, "embedding")
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), EMBED_BATCH):
        vectors += embedder.embed([c.text for c in chunks[i : i + EMBED_BATCH]])

    _stage(db, job, "indexing")
    db.execute(delete(ContentChunk).where(ContentChunk.document_id == doc.id))  # idempotent on retry
    rows = [
        ContentChunk(
            course_id=doc.course_id, document_id=doc.id, chunk_index=i, source_type=doc.source_type, text=c.text,
            page_number=c.page, slide_number=c.slide, start_seconds=c.start, end_seconds=c.end,
            figure_ref=c.figure_ref, is_generated_description=c.generated, embedding=v,
        )
        for i, (c, v) in enumerate(zip(chunks, vectors))
    ]
    db.add_all(rows)
    db.flush()

    # Verification: what we stored must match what we produced, and every row must carry a vector.
    stored = db.scalar(select(func.count()).select_from(ContentChunk).where(ContentChunk.document_id == doc.id))
    with_vec = db.scalar(select(func.count()).select_from(ContentChunk).where(ContentChunk.document_id == doc.id, ContentChunk.embedding.is_not(None)))
    if stored != len(chunks) or with_vec != len(chunks):
        raise ex.ExtractionError("Indexing verification failed: stored chunks don't match extracted chunks.")

    _stage(db, job, "topics")
    after_indexing(db, doc.course_id, rows, llm)

    doc.file_meta = {**doc.file_meta, "index": {
        "chunks": len(rows), "words": sum(len(c.text.split()) for c in chunks),
        "embedding_provider": embedder.name, "semantic_embeddings": embedder.semantic,
        "warnings": extraction.warnings,
    }}
