import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models._types import created_at, pk, utcnow


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner = relationship("User", back_populates="courses")
    documents = relationship("Document", back_populates="course", cascade="all, delete-orphan")


class Document(Base):
    """One uploaded source file. `source_type` is one of: pdf, pptx, image, video, transcript."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = pk()
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))  # relative to storage/uploads
    source_type: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    # Facts discovered by inspection. NULL means "not known", never a guess.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_text_layer: Mapped[bool | None] = mapped_column(nullable=True)
    file_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at()

    course = relationship("Course", back_populates="documents")
    jobs = relationship(
        "ProcessingJob", back_populates="document", cascade="all, delete-orphan",
        order_by="ProcessingJob.created_at.desc()",
    )


class ProcessingJob(Base):
    """Status values: queued, processing, inspected, failed.

    `inspected` means the file passed validation and structural inspection.
    Text extraction, embedding and indexing (Stage 3) will add `indexed`.
    """

    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document = relationship("Document", back_populates="jobs")
