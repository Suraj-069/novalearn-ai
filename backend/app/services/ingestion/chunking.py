"""Chunking that never crosses a provenance boundary (page, slide, figure) and merges timed cues by time window."""
import re
from dataclasses import dataclass

from app.services.ingestion.extract import RawUnit

TARGET_CHARS = 900
OVERLAP_CHARS = 120
MAX_WINDOW_SECONDS = 60.0
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Chunk:
    text: str
    page: int | None
    slide: int | None
    start: float | None
    end: float | None
    figure_ref: str | None
    generated: bool


def _split_text(text: str) -> list[str]:
    """Greedy sentence packing up to TARGET_CHARS with a small overlap for context continuity."""
    sentences = [s.strip() for s in _SENT.split(text) if s.strip()]
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        while len(s) > TARGET_CHARS * 1.5:  # a single huge "sentence" (e.g. no punctuation)
            cut = s.rfind(" ", 0, TARGET_CHARS)
            cut = cut if cut > 0 else TARGET_CHARS
            if cur:
                chunks.append(cur); cur = ""
            chunks.append(s[:cut].strip()); s = s[cut:].strip()
        if cur and len(cur) + len(s) + 1 > TARGET_CHARS:
            chunks.append(cur)
            tail = cur[-OVERLAP_CHARS:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else ""
            cur = (tail + " " + s).strip()
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def chunk_units(units: list[RawUnit]) -> list[Chunk]:
    out: list[Chunk] = []
    timed: list[RawUnit] = []

    def flush_timed():
        nonlocal timed
        if not timed:
            return
        out.append(Chunk(" ".join(u.text for u in timed), None, None, timed[0].start, timed[-1].end, None, False))
        timed = []

    for u in units:
        if u.timed:
            if timed and (len(" ".join(x.text for x in timed)) + len(u.text) > TARGET_CHARS
                          or (u.end or 0) - (timed[0].start or 0) > MAX_WINDOW_SECONDS):
                flush_timed()
            timed.append(u)
            continue
        flush_timed()
        for piece in _split_text(u.text):
            out.append(Chunk(piece, u.page, u.slide, u.start, u.end, u.figure_ref, u.generated))
    flush_timed()
    return out
