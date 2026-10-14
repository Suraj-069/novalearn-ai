import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models._types import created_at, embedding_type, pk


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)
    subtopic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text, index=False)
    question_type: Mapped[str] = mapped_column(String(20))  # mcq | short_answer | numerical
    difficulty: Mapped[str] = mapped_column(String(10))     # easy | medium | hard
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answer_key: Mapped[dict] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    rubric: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified")
    verification: Mapped[dict] = mapped_column(JSON, default=dict)      # which checks ran and what they found
    generation_method: Mapped[str] = mapped_column(String(12), default="cloze")  # cloze | llm
    embedding = mapped_column(embedding_type(), nullable=True)
    created_at: Mapped[datetime] = created_at()


class QuestionSource(Base):
    __tablename__ = "question_sources"

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_chunks.id", ondelete="CASCADE"), primary_key=True)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="quiz")  # quiz | mock_exam | diagnostic
    timed: Mapped[bool] = mapped_column(Boolean, default=False)
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at()


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"

    id: Mapped[uuid.UUID] = pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = created_at()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. overtime_seconds


class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id: Mapped[uuid.UUID] = pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessment_attempts.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    answer: Mapped[dict] = mapped_column(JSON)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    feedback: Mapped[dict | None] = mapped_column(JSON, nullable=True)
