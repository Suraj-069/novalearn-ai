import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base
from app.models._types import created_at, embedding_type, pk


class Topic(Base):
    """Hierarchical topic tree (parent_id NULL = major topic)."""

    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(10), default="auto")  # auto | user
    created_at: Mapped[datetime] = created_at()


class TopicPrerequisite(Base):
    """Directed edge: `prerequisite_id` should be learned before `topic_id`.

    Kept separate from similarity on purpose (see docs/ARCHITECTURE.md).
    """

    __tablename__ = "topic_prerequisites"

    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)
    prerequisite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin: Mapped[str] = mapped_column(String(10), default="auto")


class ContentChunk(Base):
    """A retrievable unit with full provenance. Non-applicable location fields stay NULL."""

    __tablename__ = "content_chunks"
    __table_args__ = (Index("ix_chunks_course_doc", "course_id", "document_id"),)

    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True)
    subtopic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    figure_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_generated_description: Mapped[bool] = mapped_column(Boolean, default=False)
    topic_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # True once a user chose the topic
    embedding = mapped_column(embedding_type(), nullable=True)
    created_at: Mapped[datetime] = created_at()
