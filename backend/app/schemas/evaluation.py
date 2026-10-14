from typing import Literal
import uuid

from pydantic import BaseModel, Field, model_validator


class RetrievalCaseIn(BaseModel):
    question: str = Field(min_length=4, max_length=1200)
    category: Literal["factual", "conceptual", "multi-chunk", "figure-based", "off-material"] | None = None
    reference_answer: str | None = Field(default=None, max_length=4000)
    relevant_chunk_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    should_refuse: bool = False

    @model_validator(mode="after")
    def validate_labels(self):
        if self.should_refuse:
            if self.relevant_chunk_ids:
                raise ValueError("Off-material cases must not label relevant source chunks.")
            if self.reference_answer is not None:
                raise ValueError("Off-material cases must not include a reference answer.")
        elif not self.relevant_chunk_ids or not self.reference_answer:
            raise ValueError("Answerable cases need a reference answer and at least one relevant source chunk.")
        if len(set(self.relevant_chunk_ids)) != len(self.relevant_chunk_ids):
            raise ValueError("Relevant source chunk IDs must be unique.")
        return self


class RetrievalEvaluationIn(BaseModel):
    cases: list[RetrievalCaseIn] = Field(min_length=1, max_length=50)


class SimulatedProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    skill: float = Field(ge=0, le=1, description="Probability of a correct response on a medium question.")
    slip: float = Field(default=0.15, ge=0, le=1, description="Hidden learner slip rate; independent of app BKT parameters.")
    guess: float = Field(default=0.2, ge=0, le=1, description="Hidden learner guess rate; independent of app BKT parameters.")
    learning: float = Field(default=0.08, ge=0, le=1, description="Synthetic latent mastery gain per exposure.")
    forgetting: float = Field(default=0.01, ge=0, le=1, description="Synthetic per-session decay for unpracticed topics.")


class PersonalizationEvaluationIn(BaseModel):
    sessions: int = Field(default=5, ge=5, le=12)
    questions_per_session: int = Field(default=5, ge=1, le=20)
    runs: int = Field(default=5, ge=2, le=20)
    seed: int = Field(default=17, ge=0, le=2_000_000_000)
    profiles: list[SimulatedProfileIn] = Field(
        default_factory=lambda: [
            SimulatedProfileIn(name="Weak", skill=0.28, slip=0.24, guess=0.20, learning=0.13, forgetting=0.02),
            SimulatedProfileIn(name="Average", skill=0.55, slip=0.16, guess=0.18, learning=0.09, forgetting=0.01),
            SimulatedProfileIn(name="Strong", skill=0.82, slip=0.09, guess=0.16, learning=0.05, forgetting=0.005),
            SimulatedProfileIn(name="Forgetful", skill=0.66, slip=0.21, guess=0.20, learning=0.04, forgetting=0.08),
        ],
        min_length=1,
        max_length=10,
    )


EvaluationKind = Literal["retrieval", "personalization"]
