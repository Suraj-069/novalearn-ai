import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TopicOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    description: str
    origin: str
    chunk_count: int
    source_counts: dict[str, int]          # chunks per source type -> content coverage
    documents: list[dict]                   # {id, filename, chunks}
    prerequisites: list[dict]               # {id, name, origin}
    mastery: float | None = None            # learner-model estimate; None until the student has answered questions on it
    mastery_evidence: int = 0               # number of quiz/conversation evidence events


class TopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=400)
    parent_id: uuid.UUID | None = None


class TopicPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=400)
    parent_id: uuid.UUID | None = None
    clear_parent: bool = False


class PrereqIn(BaseModel):
    prerequisite_id: uuid.UUID


class ChunkPatch(BaseModel):
    topic_id: uuid.UUID | None = None


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    mode: str | None = Field(default=None, pattern="^(explain|simple|detailed|example|compare|summary)$")
    allow_general: bool = False


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list[dict]
    grounded: bool | None
    mode: str | None = None
    created_at: datetime


class ChatOut(BaseModel):
    conversation_id: uuid.UUID
    user_message: MessageOut
    assistant_message: MessageOut


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    topic_id: uuid.UUID | None
    created_at: datetime
