"""Citation records. Built only from chunks that exist in the database."""
import re

from app.models.course import Document
from app.models.knowledge import ContentChunk
from app.services.providers.text import tokens


def excerpt(text: str, max_chars: int = 420) -> str:
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[: max_chars].rsplit(" ", 1)[0] + "…"


def citation_for(n: int, chunk: ContentChunk, doc: Document) -> dict:
    return {
        "n": n,
        "chunk_id": str(chunk.id),
        "document_id": str(doc.id),
        "filename": doc.original_filename,
        "source_type": chunk.source_type,
        "page": chunk.page_number,
        "slide": chunk.slide_number,
        "start_seconds": chunk.start_seconds,
        "end_seconds": chunk.end_seconds,
        "figure_ref": chunk.figure_ref,
        "ai_generated": chunk.is_generated_description,
        "excerpt": excerpt(chunk.text),
        "available": True,
    }


def best_sentences(query: str, text: str, limit: int = 2) -> str:
    """Pick the sentences most relevant to the query (used for extractive answers)."""
    q = set(tokens(query))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    scored = sorted(((len(q & set(tokens(s))), -i, s) for i, s in enumerate(sents)), reverse=True)
    picked = sorted(scored[:limit], key=lambda x: -x[1])  # restore document order
    return " ".join(s for _, _, s in picked)
