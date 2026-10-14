"""Source grounded revision cards drawn from verified question bank items."""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course
from app.database.session import get_db
from app.models.assessment import Question, QuestionSource
from app.models.course import Document
from app.models.knowledge import ContentChunk, Topic
from app.models.user import User
from app.services.assessment.results import _correct_display
from app.services.learner.mastery import latest_mastery
from app.services.learner.recommend import WEAK
from app.services.retrieval.citations import citation_for

router = APIRouter(prefix="/api", tags=["revision"])


@router.get("/courses/{course_id}/revision-cards")
def revision_cards(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Return existing verified, cited questions for topics currently below the weak threshold."""
    owned_course(course_id, user, db)
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id).order_by(Topic.name)).all()
    states = latest_mastery(db, user.id, [topic.id for topic in topics])
    weak_ids = {topic.id for topic in topics if topic.id in states and states[topic.id].mastery < WEAK}
    if not weak_ids:
        return []

    rows = db.execute(
        select(Question, Topic, ContentChunk, Document)
        .join(Topic, Topic.id == Question.topic_id)
        .join(QuestionSource, QuestionSource.question_id == Question.id)
        .join(ContentChunk, ContentChunk.id == QuestionSource.chunk_id)
        .join(Document, Document.id == ContentChunk.document_id)
        .where(Question.course_id == course_id, Question.topic_id.in_(weak_ids),
               Question.verification_status == "verified", ContentChunk.course_id == course_id)
        .order_by(Topic.name, Question.created_at, Question.id, ContentChunk.chunk_index)
        .limit(60)
    ).all()
    out, seen = [], set()
    for question, topic, chunk, document in rows:
        # One card per question; retain all source citations that actually support it.
        if question.id in seen:
            continue
        seen.add(question.id)
        source_rows = db.execute(
            select(ContentChunk, Document)
            .join(QuestionSource, QuestionSource.chunk_id == ContentChunk.id)
            .join(Document, Document.id == ContentChunk.document_id)
            .where(QuestionSource.question_id == question.id, ContentChunk.course_id == course_id)
            .order_by(ContentChunk.chunk_index)
        ).all()
        out.append({
            "id": str(question.id), "topic_id": str(topic.id), "topic": topic.name,
            "front": question.text, "answer": _correct_display(question),
            "explanation": question.explanation,
            "citations": [citation_for(i + 1, source, doc) for i, (source, doc) in enumerate(source_rows)],
        })
    return out
