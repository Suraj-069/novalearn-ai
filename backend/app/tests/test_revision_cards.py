"""Revision cards reuse only verified, cited questions from a student's own weak topics."""
import uuid

from sqlalchemy import select

from app.models.assessment import Question, QuestionSource
from app.models.knowledge import ContentChunk, Topic
from app.models.learner import TopicMasteryHistory


def _question(db, course_id, topic_id, chunk_id, *, verified=True, sourced=True):
    q = Question(
        course_id=course_id, topic_id=topic_id, text="What does the first law conserve?",
        normalized_text="what does the first law conserve", question_type="short_answer", difficulty="easy",
        options=None, answer_key={"answers": ["energy"]}, explanation="Energy is conserved in the first law.",
        rubric=None, verification_status="verified" if verified else "unverified", verification={}, generation_method="cloze",
    )
    db.add(q)
    db.flush()
    if sourced:
        db.add(QuestionSource(question_id=q.id, chunk_id=chunk_id))
    return q


def _weak_history(db, user_id, topic_id):
    db.add(TopicMasteryHistory(user_id=user_id, topic_id=topic_id, previous_mastery=0.5,
                               new_mastery=0.2, was_correct=False, difficulty="easy",
                               attempt_id=None, question_id=None, evidence={}))
    db.flush()


def test_revision_cards_only_return_verified_cited_questions_for_weak_topics(client, alice, thermo, db):
    course_id = uuid.UUID(thermo["course"]["id"])
    topic = db.scalar(select(Topic).where(Topic.course_id == course_id))
    chunk_id = db.execute(select(ContentChunk.id).where(ContentChunk.course_id == course_id)).scalars().first()
    user_id = uuid.UUID(client.get("/api/auth/me", headers=alice).json()["id"])
    _weak_history(db, user_id, topic.id)
    verified = _question(db, course_id, topic.id, chunk_id)
    _question(db, course_id, topic.id, chunk_id, verified=False)
    _question(db, course_id, topic.id, chunk_id, sourced=False)
    db.commit()

    response = client.get(f"/api/courses/{course_id}/revision-cards", headers=alice)
    assert response.status_code == 200, response.text
    cards = response.json()
    assert len(cards) == 1
    assert cards[0]["id"] == str(verified.id)
    assert cards[0]["front"] == verified.text
    assert cards[0]["answer"] == "energy"
    assert cards[0]["explanation"] == verified.explanation
    assert cards[0]["topic"] == topic.name
    assert cards[0]["citations"][0]["chunk_id"] == str(chunk_id)
    assert cards[0]["citations"][0]["filename"]


def test_revision_cards_require_course_ownership_and_weak_evidence(client, alice, bob, thermo, db):
    course_id = uuid.UUID(thermo["course"]["id"])
    topic = db.scalar(select(Topic).where(Topic.course_id == course_id))
    stranger = client.get("/api/auth/me", headers=bob).json()
    assert client.get(f"/api/courses/{course_id}/revision-cards", headers=bob).status_code == 404
    assert client.get(f"/api/courses/{course_id}/revision-cards", headers=alice).json() == []
    _weak_history(db, uuid.UUID(stranger["id"]), topic.id)
    db.commit()
    # The owner's endpoint must not use another student's mastery to select weak topics.
    assert client.get(f"/api/courses/{course_id}/revision-cards", headers=alice).json() == []
