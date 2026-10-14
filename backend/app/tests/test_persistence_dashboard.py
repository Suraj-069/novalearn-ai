"""Persistence across sessions and database-backed dashboard."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.course import Course
from app.models.knowledge import Topic
from app.models.learner import RevisionRecommendation, TopicMasteryHistory
from app.models.user import User
from app.tests.samples import make_text_pdf


def test_data_survives_new_session(client, alice, course):
    client.post(f"/api/courses/{course['id']}/documents", headers=alice,
                files={"file": ("a.pdf", make_text_pdf(["x"]), "application/pdf")})
    s = SessionLocal()  # a brand-new session, as after a server restart
    try:
        c = s.scalar(select(Course))
        assert c.title == "Thermodynamics" and len(c.documents) == 1
        assert c.documents[0].jobs[0].status == "indexed"
    finally:
        s.close()


def test_empty_dashboard_is_truthful(client, alice):
    d = client.get("/api/dashboard", headers=alice).json()
    assert d["course_count"] == 0 and d["mastery"] == [] and d["weak_topics"] == []
    assert d["recommendations"] == [] and d["recent_assessments"] == []


def test_dashboard_reports_latest_mastery_from_history(client, alice, course, db):
    user = db.scalar(select(User))
    t1 = Topic(course_id=uuid.UUID(course["id"]), name="Entropy")
    t2 = Topic(course_id=uuid.UUID(course["id"]), name="First Law")
    db.add_all([t1, t2]); db.flush()
    now = datetime.now(timezone.utc)
    db.add_all([
        TopicMasteryHistory(user_id=user.id, topic_id=t1.id, previous_mastery=0.3, new_mastery=0.2, was_correct=False,
                            difficulty="easy", created_at=now - timedelta(days=2)),
        TopicMasteryHistory(user_id=user.id, topic_id=t1.id, previous_mastery=0.2, new_mastery=0.35, was_correct=True,
                            difficulty="easy", created_at=now - timedelta(days=1)),
        TopicMasteryHistory(user_id=user.id, topic_id=t2.id, previous_mastery=0.5, new_mastery=0.8, was_correct=True,
                            difficulty="medium", created_at=now),
        RevisionRecommendation(user_id=user.id, course_id=uuid.UUID(course["id"]), topic_id=t1.id, kind="review_topic",
                               reason="Mastery estimate for Entropy is 35%."),
    ])
    db.commit()
    d = client.get("/api/dashboard", headers=alice).json()
    by_name = {m["topic_name"]: m["mastery"] for m in d["mastery"]}
    assert by_name == {"Entropy": 0.35, "First Law": 0.8}  # latest row wins, not the earlier 0.2
    assert [w["topic_name"] for w in d["weak_topics"]] == ["Entropy"]
    assert d["recommendations"][0]["reason"].startswith("Mastery estimate")


def test_deleting_course_cascades_topics_and_history(client, alice, course, db):
    user = db.scalar(select(User))
    t = Topic(course_id=uuid.UUID(course["id"]), name="X"); db.add(t); db.flush()
    db.add(TopicMasteryHistory(user_id=user.id, topic_id=t.id, previous_mastery=0.5, new_mastery=0.6, was_correct=True, difficulty="easy"))
    db.commit()
    assert client.delete(f"/api/courses/{course['id']}", headers=alice).status_code == 204
    db.expire_all()
    assert db.scalar(select(Topic)) is None and db.scalar(select(TopicMasteryHistory)) is None
