"""Duplicate prevention: exact (normalised) and near-duplicate (embedding similarity) against the student's
previous questions in the course and against the batch being built."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.assessment import Assessment, AssessmentQuestion, Question
from app.services.assessment.common import normalize
from app.services.retrieval.search import cosine

LEXICAL_THRESHOLD = 0.82
SEMANTIC_THRESHOLD = 0.92


class DuplicateIndex:
    def __init__(self, db: Session, user_id, course_id, embedder):
        self.embedder = embedder
        self.thr = SEMANTIC_THRESHOLD if embedder.semantic else LEXICAL_THRESHOLD
        rows = db.execute(
            select(Question.normalized_text, Question.embedding)
            .join(AssessmentQuestion, AssessmentQuestion.question_id == Question.id)
            .join(Assessment, Assessment.id == AssessmentQuestion.assessment_id)
            .where(Assessment.user_id == user_id, Assessment.course_id == course_id)
            .order_by(Question.created_at.desc()).limit(1000)
        ).all()
        self.norms = {r[0] for r in rows}
        self.vecs = [r[1] for r in rows if r[1] is not None]
        self.history_size = len(rows)

    def check(self, text: str) -> tuple[bool, list[float] | None]:
        """Returns (is_duplicate, embedding)."""
        try:
            vec = self.embedder.embed([text])[0]
        except Exception:
            vec = None
        if normalize(text) in self.norms:
            return True, vec
        if vec is not None:
            return any(cosine(vec, v) >= self.thr for v in self.vecs), vec
        return False, None

    def add(self, text: str, vec: list[float] | None) -> None:
        self.norms.add(normalize(text))
        if vec is not None:
            self.vecs.append(vec)
