"""Import every model so Base.metadata (and Alembic) sees all tables."""
from app.models.assessment import (  # noqa: F401
    Assessment, AssessmentAttempt, AssessmentQuestion, Question, QuestionSource, StudentAnswer,
)
from app.models.course import Course, Document, ProcessingJob  # noqa: F401
from app.models.evaluation import EvaluationMetric, EvaluationRun  # noqa: F401
from app.models.knowledge import ContentChunk, Topic, TopicPrerequisite  # noqa: F401
from app.models.learner import RevisionRecommendation, TopicMasteryHistory  # noqa: F401
from app.models.tutoring import Conversation, ConversationMessage  # noqa: F401
from app.models.user import User  # noqa: F401
