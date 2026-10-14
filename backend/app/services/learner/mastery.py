"""Mastery persistence: an append-only event log, so every estimate is auditable."""
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentAttempt, Question
from app.models.learner import TopicMasteryHistory
from app.services.learner import bkt


@dataclass
class MasteryState:
    mastery: float
    evidence: int
    updated_at: datetime


def latest_mastery(db: Session, user_id, topic_ids: list | None = None) -> dict[uuid.UUID, MasteryState]:
    q = select(TopicMasteryHistory).where(TopicMasteryHistory.user_id == user_id).order_by(TopicMasteryHistory.created_at, TopicMasteryHistory.id)
    if topic_ids is not None:
        q = q.where(TopicMasteryHistory.topic_id.in_(topic_ids))
    out: dict[uuid.UUID, MasteryState] = {}
    for h in db.scalars(q):
        prev = out.get(h.topic_id)
        out[h.topic_id] = MasteryState(h.new_mastery, (prev.evidence if prev else 0) + 1, h.created_at)
    return out


def record_answer(db: Session, *, user_id, question: Question, score: float, attempt: AssessmentAttempt, chunk_ids: list[str]) -> TopicMasteryHistory | None:
    """Update the question's topic from one graded answer. Questions with no topic tag give no evidence."""
    if question.topic_id is None:
        return None
    prev_row = db.scalars(select(TopicMasteryHistory).where(TopicMasteryHistory.user_id == user_id, TopicMasteryHistory.topic_id == question.topic_id)
                          .order_by(TopicMasteryHistory.created_at.desc(), TopicMasteryHistory.id.desc()).limit(1)).first()
    prev = prev_row.new_mastery if prev_row else bkt.P_INIT
    new, params = bkt.update(prev, score, question.question_type, question.difficulty)
    row = TopicMasteryHistory(
        user_id=user_id, topic_id=question.topic_id, previous_mastery=prev, new_mastery=new, was_correct=score >= 0.5,
        difficulty=question.difficulty, attempt_id=attempt.id, question_id=question.id,
        evidence={"score": score, "question_type": question.question_type, "bkt": params, "source_chunk_ids": chunk_ids,
                  "subtopic_id": str(question.subtopic_id) if question.subtopic_id else None, "first_evidence": prev_row is None},
    )
    db.add(row)
    db.flush()
    return row


def record_conversation_signal(db: Session, *, user_id, topic_id, conversation_id, question: str,
                               prior_user_turns: int = 0) -> TopicMasteryHistory | None:
    """Record one tiny, auditable struggle signal per conversation/topic; never treats fluent text as mastery."""
    text = question.casefold()
    if any(term in text for term in ("prerequisite", "what should i know before", "what do i need to know first")):
        signal = "asked_for_prerequisite"
        note = "Student explicitly asked what to learn first."
    elif any(term in text for term in ("simpler", "more simply", "don't understand", "do not understand", "confused")):
        signal = "requested_simpler_explanation"
        note = "Student explicitly requested simpler help or reported confusion."
    elif prior_user_turns >= 2:
        signal = "repeated_topic_questions"
        note = "Student asked multiple questions in this topic conversation."
    else:
        return None

    history = list(db.scalars(select(TopicMasteryHistory).where(
        TopicMasteryHistory.user_id == user_id, TopicMasteryHistory.topic_id == topic_id
    ).order_by(TopicMasteryHistory.created_at, TopicMasteryHistory.id)))
    if any((row.evidence or {}).get("conversation_id") == str(conversation_id) for row in history):
        return None
    previous = history[-1].new_mastery if history else bkt.P_INIT
    new = max(bkt.LOW, previous - 0.02)
    row = TopicMasteryHistory(
        user_id=user_id, topic_id=topic_id, previous_mastery=previous, new_mastery=new,
        was_correct=False, difficulty="medium", attempt_id=None, question_id=None,
        evidence={"source": "tutor_conversation_signal", "signal": signal, "note": note,
                  "weight": -0.02, "conversation_id": str(conversation_id), "first_evidence": not history},
    )
    db.add(row)
    db.flush()
    return row
