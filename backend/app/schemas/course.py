import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be blank")
        return v


class CourseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    stage: str
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    course_id: uuid.UUID
    original_filename: str
    source_type: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    slide_count: int | None
    duration_seconds: float | None
    has_text_layer: bool | None
    file_meta: dict
    created_at: datetime
    job: JobOut | None = None


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    topic_count: int = 0
    status_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
