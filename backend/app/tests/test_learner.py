"""Learner model (BKT), recommendations, spaced repetition, analytics and next-assessment personalisation."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.learner import RevisionRecommendation, TopicMasteryHistory
from app.models.user import User
from app.services.learner import bkt
from app.services.learner.mastery import latest_mastery, record_conversation_signal
from app.services.tutoring.service import _learner_style
from app.services.learner.recommend import generate_recommendations, review_interval_days
from app.services.learner.schedule import build_study_plan
from app.tests.test_assessment import answers_for, big, quiz, take  # noqa: F401  (fixtures reused)


# ---------------- BKT ----------------
def test_first_update_starts_from_the_prior_not_from_assumed_knowledge():
    new, p = bkt.update(bkt.P_INIT, 1.0, "short_answer", "medium")
    assert bkt.P_INIT == 0.20 and new > bkt.P_INIT
    assert bkt.update(bkt.P_INIT, 0.0, "short_answer", "medium")[0] < bkt.P_INIT


def test_bkt_is_bounded_and_monotone_with_evidence():
    p = bkt.P_INIT
    for _ in range(200):
        p = bkt.update(p, 1.0, "numerical", "hard")[0]
    assert p <= 0.98
    q = 0.9
    for _ in range(200):
        q = bkt.update(q, 0.0, "numerical", "easy")[0]
    assert q >= 0.02
    seq = [bkt.P_INIT]
    for _ in range(5):
        seq.append(bkt.update(seq[-1], 1.0, "short_answer", "medium")[0])
    assert seq == sorted(seq) and seq[1] > seq[0] and seq[2] > seq[1]  # rises with evidence, until the cap
    assert seq[1] < 0.75  # a single correct answer is not enough to call a topic mastered


def test_partial_credit_lands_between_wrong_and_right():
    wrong, half, right = (bkt.update(0.4, s, "short_answer", "hard")[0] for s in (0.0, 0.5, 1.0))
    assert wrong < half < right


def test_a_lucky_guess_counts_for_less_than_a_recalled_answer():
    mcq = bkt.update(0.3, 1.0, "mcq", "easy")[0]
    recall = bkt.update(0.3, 1.0, "short_answer", "easy")[0]
    assert recall > mcq  # guessing an MCQ is far more likely than guessing a free-text answer


def test_wrong_answer_on_a_hard_question_hurts_less_than_on_an_easy_one():
    assert bkt.update(0.6, 0.0, "short_answer", "hard")[0] > bkt.update(0.6, 0.0, "short_answer", "easy")[0]


def test_conversation_struggle_signal_is_small_auditable_and_once_per_conversation(client, alice, big, db):
    (topic, *_), uid, _ = _setup(client, alice, big, db)
    conversation = uuid.uuid4()
    event = record_conversation_signal(db, user_id=uid, topic_id=uuid.UUID(topic["id"]),
        conversation_id=conversation, question="Can you explain this more simply?")
    assert event is not None and event.previous_mastery == bkt.P_INIT
    assert event.new_mastery == pytest.approx(bkt.P_INIT - 0.02)
    assert event.evidence["source"] == "tutor_conversation_signal"
    assert event.evidence["signal"] == "requested_simpler_explanation"
    assert event.attempt_id is None and event.question_id is None
    assert record_conversation_signal(db, user_id=uid, topic_id=uuid.UUID(topic["id"]),
        conversation_id=conversation, question="I am confused") is None
    assert record_conversation_signal(db, user_id=uid, topic_id=uuid.UUID(topic["id"]),
        conversation_id=uuid.uuid4(), question="Thanks") is None


def test_tutor_style_uses_low_or_high_mastery_without_claiming_it_as_source_fact(client, alice, big, db):
    (topic, *_), uid, _ = _setup(client, alice, big, db)
    tid = uuid.UUID(topic["id"])
    _hist(db, uid, topic["id"], 0.25)
    low = _learner_style(db, uid, [tid])
    assert "short, plain steps" in low and "Do not mention learner estimates" in low
    _hist(db, uid, topic["id"], 0.85)
    high = _learner_style(db, uid, [tid])
    assert "challenging follow-up question" in high and "Do not mention learner estimates" in high


# ---------------- recommendations ----------------
def _setup(client, alice, big, db):
    topics = [t for t in client.get(f"/api/courses/{big['id']}/topics", headers=alice).json() if t["chunk_count"] > 0]
    assert len(topics) >= 2
    return topics, db.scalar(select(User.id)), uuid.UUID(big["id"])


def _hist(db, uid, topic_id, m, when=None):
    db.add(TopicMasteryHistory(user_id=uid, topic_id=uuid.UUID(topic_id), previous_mastery=0.2, new_mastery=m, was_correct=m > 0.5, difficulty="easy", evidence={},
                               **({"created_at": when} if when else {})))
    db.commit()


def test_weak_topic_with_unassessed_prerequisite_recommends_revisiting_it(client, alice, big, db):
    (a, b, *_), uid, cid = _setup(client, alice, big, db)
    assert client.post(f"/api/topics/{a['id']}/prerequisites", headers=alice, json={"prerequisite_id": b["id"]}).status_code == 201
    _hist(db, uid, a["id"], 0.12)
    recs = generate_recommendations(db, uid, cid); db.commit()
    r = next(x for x in recs if x.kind == "revisit_prerequisite")
    assert str(r.topic_id) == b["id"] and r.evidence["prerequisite_mastery"] is None and r.evidence["mastery_estimate"] == 0.12
    assert b["name"] in r.reason and "12%" in r.reason and "not assessed" in r.reason


def test_strong_topic_gets_a_challenge_and_a_spaced_revision_date(client, alice, big, db):
    (a, *_), uid, cid = _setup(client, alice, big, db)
    _hist(db, uid, a["id"], 0.85)
    recs = generate_recommendations(db, uid, cid); db.commit()
    kinds = {x.kind: x for x in recs if str(x.topic_id) == a["id"]}
    assert "challenge" in kinds and kinds["challenge"].evidence["suggested_difficulty"] == "hard"
    due = kinds["revise_later"].due_at
    due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
    assert kinds["revise_later"].evidence["interval_days"] == 7 and timedelta(days=6, hours=23) < due - datetime.now(timezone.utc) < timedelta(days=7, minutes=1)


def test_review_intervals_grow_with_mastery():
    ms = [0.3, 0.55, 0.7, 0.85, 0.95]
    days = [review_interval_days(m) for m in ms]
    assert days == sorted(days) and days[0] == 1 and days[-1] == 14


def test_study_plan_uses_weak_topics_and_documented_decay_without_claiming_learning():
    from datetime import date
    topics = [{"id": "weak", "name": "Weak topic", "mastery": 0.2},
              {"id": "strong", "name": "Strong topic", "mastery": 0.9}]
    result = build_study_plan(topics, today=date(2026, 1, 1), exam_date=date(2026, 1, 3), hours_per_day=0.5)
    assert len(result["days"]) == 3
    assert result["days"][0]["tasks"][0]["topic_id"] == "weak"
    assert result["days"][1]["tasks"][0]["topic_id"] == "strong"
    assert result["days"][2]["tasks"][0]["topic_id"] == "weak"
    assert result["days"][2]["tasks"][0]["estimated_recall"] < result["days"][0]["tasks"][0]["estimated_recall"]
    assert "exp(-days / 14)" in result["formula"]


def test_study_plan_rejects_past_exam_date_and_unusable_daily_time():
    from datetime import date
    with pytest.raises(ValueError, match="today or later"):
        build_study_plan([], today=date(2026, 1, 2), exam_date=date(2026, 1, 1), hours_per_day=1)
    with pytest.raises(ValueError, match="at least one"):
        build_study_plan([], today=date(2026, 1, 1), exam_date=date(2026, 1, 1), hours_per_day=0.25)


def test_study_plan_endpoint_is_course_scoped_and_uses_real_topic_estimates(client, alice, bob, big, db):
    from datetime import date, timedelta
    (topic, *_), _, _ = _setup(client, alice, big, db)
    from app.core.security import decode_access_token
    uid = uuid.UUID(decode_access_token(alice["Authorization"].split()[1]))
    _hist(db, uid, topic["id"], 0.12)
    body = {"exam_date": (date.today() + timedelta(days=1)).isoformat(), "hours_per_day": 0.5}
    response = client.post(f"/api/courses/{big['id']}/study-plan", headers=alice, json=body)
    assert response.status_code == 200
    result = response.json()
    assert len(result["days"]) == 2 and result["days"][0]["tasks"]
    assert result["days"][0]["tasks"][0]["topic_id"] == topic["id"]
    assert "exp(-days / 14)" in result["formula"]
    assert client.post(f"/api/courses/{big['id']}/study-plan", headers=bob, json=body).status_code == 404


def test_recommendations_change_when_performance_changes(client, alice, big, db):
    (a, *_), uid, cid = _setup(client, alice, big, db)
    _hist(db, uid, a["id"], 0.15)
    first = {r.kind for r in generate_recommendations(db, uid, cid)}; db.commit()
    assert "easier_practice" in first and "challenge" not in first
    _hist(db, uid, a["id"], 0.88)
    second = {r.kind for r in generate_recommendations(db, uid, cid)}; db.commit()
    assert "challenge" in second and "easier_practice" not in second
    statuses = [r.status for r in db.scalars(select(RevisionRecommendation))]
    assert "superseded" in statuses and statuses.count("open") == len([1 for r in db.scalars(select(RevisionRecommendation)) if r.status == "open"])


def test_unassessed_topics_are_flagged_once_the_student_has_started(client, alice, big, db):
    (a, b, *_), uid, cid = _setup(client, alice, big, db)
    _hist(db, uid, a["id"], 0.5)
    recs = generate_recommendations(db, uid, cid)
    assert any(r.kind == "assess_topic" and str(r.topic_id) == b["id"] and r.evidence["evidence_count"] == 0 for r in recs)
    assert not any(str(r.topic_id) == b["id"] and r.kind in ("practice", "challenge") for r in recs)  # nothing assumed about b


def test_no_recommendations_before_any_evidence(client, alice, big, db):
    _, uid, cid = _setup(client, alice, big, db)
    assert generate_recommendations(db, uid, cid) == []


def test_recommendations_endpoint_and_dismiss(client, alice, big, db):
    a = quiz(client, alice, big["id"], num_questions=4).json()
    take(client, alice, db, a["id"], correct=False)
    recs = client.get(f"/api/courses/{big['id']}/recommendations", headers=alice).json()
    assert recs and all(r["reason"] and r["evidence"] for r in recs)
    assert client.post(f"/api/recommendations/{recs[0]['id']}/dismiss", headers=alice).status_code == 204
    assert len(client.get(f"/api/courses/{big['id']}/recommendations", headers=alice).json()) == len(recs) - 1


def test_cannot_dismiss_someone_elses_recommendation(client, alice, bob, big, db):
    take(client, alice, db, quiz(client, alice, big["id"]).json()["id"], correct=False)
    rid = client.get(f"/api/courses/{big['id']}/recommendations", headers=alice).json()[0]["id"]
    assert client.post(f"/api/recommendations/{rid}/dismiss", headers=bob).status_code == 404


# ---------------- next assessment ----------------
def test_next_assessment_is_a_diagnostic_until_there_is_evidence_then_targets_weak_topics(client, alice, big, db):
    nxt = client.get(f"/api/courses/{big['id']}/next-assessment", headers=alice).json()
    assert nxt["mode"] == "diagnostic" and nxt["topic_ids"] == [] and "haven't taken" in nxt["reason"]
    (a, b, *_), uid, cid = _setup(client, alice, big, db)
    _hist(db, uid, a["id"], 0.1); _hist(db, uid, b["id"], 0.9)
    nxt = client.get(f"/api/courses/{big['id']}/next-assessment", headers=alice).json()
    assert nxt["mode"] == "quiz" and nxt["topic_ids"][0] == a["id"] and "10%" in nxt["reason"]
    # the suggestion is directly usable to create the next quiz
    r = client.post(f"/api/courses/{big['id']}/assessments", headers=alice, json={k: nxt[k] for k in ("mode", "topic_ids", "num_questions", "difficulty", "types")})
    assert r.status_code == 201


# ---------------- analytics + dashboard ----------------
def test_analytics_is_built_from_real_attempts(client, alice, big, db):
    empty = client.get(f"/api/courses/{big['id']}/analytics", headers=alice).json()
    assert empty["assessments"] == [] and empty["timeline"] == [] and all(m["status"] == "not_assessed" and m["mastery"] is None for m in empty["mastery"])
    assert len(empty["activity"]) == 14 and "estimate" in empty["note"]

    a1 = quiz(client, alice, big["id"], num_questions=5, seed=1).json(); take(client, alice, db, a1["id"], correct=True)
    a2 = quiz(client, alice, big["id"], num_questions=3, seed=2).json(); take(client, alice, db, a2["id"], correct=False)
    d = client.get(f"/api/courses/{big['id']}/analytics", headers=alice).json()
    assert [x["accuracy"] for x in d["assessments"]] == [1.0, 0.0]
    assert len(d["timeline"]) == len(a1["questions"]) + len(a2["questions"])
    assert sum(x["answered"] for x in d["difficulty"]) == len(d["timeline"])
    assert {x["difficulty"] for x in d["difficulty"]} == {"easy", "medium", "hard"}
    assert sum(x["answers"] for x in d["activity"]) == len(d["timeline"]) and sum(x["attempts"] for x in d["activity"]) == 2
    for m in d["mastery"]:
        assert (m["mastery"] is None) == (m["evidence"] == 0)
    history = client.get(f"/api/courses/{big['id']}/attempts", headers=alice).json()
    assert len(history) == 2 and history[0]["score"] == len(a1["questions"])
    assert [x["status"] for x in client.get(f"/api/courses/{big['id']}/assessments", headers=alice).json()] == ["completed", "completed"]


def test_dashboard_reflects_assessment_results(client, alice, big, db):
    take(client, alice, db, quiz(client, alice, big["id"], num_questions=4).json()["id"], correct=False)
    d = client.get("/api/dashboard", headers=alice).json()
    assert d["mastery"] and d["weak_topics"] and all(w["mastery"] < 0.5 for w in d["weak_topics"])
    assert len(d["recent_assessments"]) == 1 and d["recent_assessments"][0]["score"] == 0
    assert d["recommendations"] and any(a["kind"] == "assessment" for a in d["recent_activity"])


def test_mastery_is_per_user(client, alice, bob, big, db):
    take(client, alice, db, quiz(client, alice, big["id"]).json()["id"], correct=True)
    assert client.get("/api/dashboard", headers=bob).json()["mastery"] == []
    assert latest_mastery(db, uuid.uuid4()) == {}


def test_topic_list_and_dashboard_show_real_mastery_and_upcoming_revision(client, alice, big, db):
    (a, b, *_), uid, cid = _setup(client, alice, big, db)
    before = {t["id"]: t for t in client.get(f"/api/courses/{big['id']}/topics", headers=alice).json()}
    assert all(t["mastery"] is None and t["mastery_evidence"] == 0 for t in before.values())
    _hist(db, uid, a["id"], 0.3); _hist(db, uid, a["id"], 0.85)
    generate_recommendations(db, uid, cid); db.commit()
    after = {t["id"]: t for t in client.get(f"/api/courses/{big['id']}/topics", headers=alice).json()}
    assert after[a["id"]]["mastery"] == 0.85 and after[a["id"]]["mastery_evidence"] == 2 and after[b["id"]]["mastery"] is None
    d = client.get("/api/dashboard", headers=alice).json()
    (rev,) = d["upcoming_revisions"]
    assert rev["topic_name"] == a["name"] and rev["is_due"] is False
