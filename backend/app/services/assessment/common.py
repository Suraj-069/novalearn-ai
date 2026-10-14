"""Shared assessment types and small helpers."""
import re
from dataclasses import dataclass, field

from app.services.providers.text import tokens

DIFFICULTIES = ("easy", "medium", "hard")
QUESTION_TYPES = ("mcq", "short_answer", "numerical")


@dataclass
class Candidate:
    """A proposed question. Nothing becomes a Question row until it passes verification and de-duplication."""
    text: str
    qtype: str
    difficulty: str
    answer_key: dict
    explanation: str
    chunk_id: object
    topic_id: object
    subtopic_id: object
    method: str                      # cloze | llm
    options: list[dict] | None = None   # [{"id","text","from_topic"?}]
    rubric: dict | None = None
    source_text: str = ""            # the evidence the question was built from


def normalize(text: str) -> str:
    """Canonical form for exact-duplicate detection (case, punctuation, stop-words and inflection ignored)."""
    return " ".join(tokens(re.sub(r"_+", " blank ", text), drop_stop=False))


@dataclass
class Rejection:
    reason: str
    detail: str = ""


@dataclass
class GenerationReport:
    requested: int = 0
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
