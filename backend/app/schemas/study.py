from datetime import date
from pydantic import BaseModel, Field


class StudyPlanIn(BaseModel):
    exam_date: date
    hours_per_day: float = Field(ge=0.25, le=16)
