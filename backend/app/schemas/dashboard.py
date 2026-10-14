import uuid
from datetime import datetime

from pydantic import BaseModel


class TopicMasteryOut(BaseModel):
    topic_id: uuid.UUID
    topic_name: str
    course_id: uuid.UUID
    mastery: float          # 0..1 estimate, never a measurement
    updated_at: datetime


class ActivityOut(BaseModel):
    kind: str               # upload | assessment
    label: str
    course_id: uuid.UUID
    at: datetime


class RecommendationOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    topic_id: uuid.UUID | None
    kind: str
    reason: str


class AssessmentSummaryOut(BaseModel):
    attempt_id: uuid.UUID
    course_id: uuid.UUID
    score: float
    max_score: float
    submitted_at: datetime


class UpcomingRevisionOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    topic_name: str | None
    due_at: datetime
    is_due: bool
    reason: str


class DashboardOut(BaseModel):
    course_count: int
    document_count: int
    indexed_document_count: int
    topic_count: int
    mastery: list[TopicMasteryOut]
    weak_topics: list[TopicMasteryOut]
    recent_activity: list[ActivityOut]
    recommendations: list[RecommendationOut]
    recent_assessments: list[AssessmentSummaryOut]
    upcoming_revisions: list[UpcomingRevisionOut] = []
