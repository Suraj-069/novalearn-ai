import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AssessmentCreate(BaseModel):
    mode: Literal["quiz", "mock_exam", "diagnostic"] = "quiz"
    topic_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    num_questions: int = Field(default=8, ge=1, le=30)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    types: list[Literal["mcq", "short_answer", "numerical"]] = Field(default_factory=lambda: ["mcq", "short_answer"], min_length=1)
    timed: bool = False
    time_limit_minutes: int | None = Field(default=None, ge=1, le=240)
    seed: int | None = None  # reproducible generation (used by evaluation)

    @model_validator(mode="after")
    def _timing(self):
        if self.mode == "mock_exam":
            self.timed = True
        if self.timed and not self.time_limit_minutes:
            self.time_limit_minutes = max(5, self.num_questions * 2)  # sensible default: 2 min per question
        self.types = list(dict.fromkeys(self.types))
        return self


class SubmitIn(BaseModel):
    answers: dict[uuid.UUID, str | None] = Field(default_factory=dict, max_length=60)
