import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models._types import created_at, pk


class TopicMasteryHistory(Base):
    """One row per evidence event. Current mastery = latest row per (user, topic)."""

    __tablename__ = "topic_mastery_history"

    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    previous_mastery: Mapped[float] = mapped_column(Float)
    new_mastery: Mapped[float] = mapped_column(Float)
    was_correct: Mapped[bool] = mapped_column(Boolean)
    difficulty: Mapped[str] = mapped_column(String(10))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assessment_attempts.id", ondelete="SET NULL"), nullable=True)
    question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at()


class RevisionRecommendation(Base):
    __tablename__ = "revision_recommendations"

    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_chunks.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    created_at: Mapped[datetime] = created_at()
