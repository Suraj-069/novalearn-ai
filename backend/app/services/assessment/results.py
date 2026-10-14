"""Read models: student-facing question views, graded results, analytics and the personalised next assessment."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import Assessment, AssessmentAttempt, Question, QuestionSource, StudentAnswer
from app.models.course import Document
from app.models.knowledge import ContentChunk, Topic
from app.models.learner import RevisionRecommendation, TopicMasteryHistory
from app.services.assessment.service import assessment_questions
from app.services.learner.mastery import latest_mastery
from app.services.learner.recommend import STRONG, WEAK
from app.services.retrieval.citations import citation_for

ESTIMATE_NOTE = "Mastery is an estimate computed from your answers with a simple statistical model. It is not a measurement of what you actually know."


def topic_names(db: Session, course_id) -> dict:
    return {t.id: t.name for t in db.scalars(select(Topic).where(Topic.course_id == course_id))}


def question_view(q: Question, names: dict, position: int | None = None) -> dict:
    """What the student may see BEFORE submitting: no answer key, explanation, rubric, sources or option metadata."""
    return {"id": str(q.id), "position": position, "text": q.text, "question_type": q.question_type, "difficulty": q.difficulty,
            "topic_id": str(q.topic_id) if q.topic_id else None, "topic_name": names.get(q.topic_id),
            "options": [{"id": o["id"], "text": o["text"]} for o in (q.options or [])] or None,
            "unit": (q.answer_key or {}).get("unit") if q.question_type == "numerical" else None}


def _correct_display(q: Question) -> str:
    if q.question_type == "mcq":
        return next(o["text"] for o in q.options if o["id"] == q.answer_key["correct"])
    if q.question_type == "numerical":
        return f"{q.answer_key['value']:.6g} {q.answer_key.get('unit', '')}".strip()
    return ", ".join(q.answer_key.get("answers", []))


def _user_answer_display(q: Question, value) -> str | None:
    if value in (None, ""):
        return None
    if q.question_type == "mcq":
        return next((o["text"] for o in q.options if o["id"] == value), str(value))
    return str(value)


def next_assessment(db: Session, user_id, course_id) -> dict | None:
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id, Topic.parent_id.is_(None)).order_by(Topic.created_at)).all()
    if not topics:
        return None
    m = latest_mastery(db, user_id, [t.id for t in topics])
    if not m:
        return {"mode": "diagnostic", "topic_ids": [], "num_questions": min(10, max(4, 2 * len(topics))), "difficulty": "easy", "types": ["mcq", "short_answer"],
                "reason": "You haven't taken any assessment yet. A diagnostic spread across every topic gives your starting point."}
    ranked = sorted(topics, key=lambda t: (m[t.id].mastery if t.id in m else 0.5))
    focus = ranked[:3]
    avg = sum(m[t.id].mastery for t in focus if t.id in m) / max(1, sum(1 for t in focus if t.id in m))
    diff = "easy" if avg < WEAK else "mixed" if avg < STRONG else "hard"
    desc = ", ".join(f"{t.name} ({m[t.id].mastery:.0%} est.)" if t.id in m else f"{t.name} (not assessed)" for t in focus)
    return {"mode": "quiz", "topic_ids": [str(t.id) for t in focus], "num_questions": 8, "difficulty": diff, "types": ["mcq", "short_answer"],
            "reason": f"Targets your lowest estimates: {desc}. Difficulty is set to {diff} based on those estimates."}


def attempt_result(db: Session, attempt: AssessmentAttempt, assessment: Assessment) -> dict:
    names = topic_names(db, assessment.course_id)
    qs = assessment_questions(db, assessment.id)
    answers = {a.question_id: a for a in db.scalars(select(StudentAnswer).where(StudentAnswer.attempt_id == attempt.id))}
    items, perf = [], defaultdict(lambda: {"answered": 0, "correct": 0, "score": 0.0, "total": 0})
    for i, q in enumerate(qs):
        a = answers.get(q.id)
        cites = []
        for n, (chunk, doc) in enumerate(db.execute(select(ContentChunk, Document).join(QuestionSource, QuestionSource.chunk_id == ContentChunk.id)
                                                    .join(Document, Document.id == ContentChunk.document_id).where(QuestionSource.question_id == q.id)).all(), start=1):
            cites.append(citation_for(n, chunk, doc))
        value = (a.answer or {}).get("value") if a else None
        answered = a is not None and a.score is not None
        p = perf[q.topic_id]
        p["total"] += 1
        if answered:
            p["answered"] += 1; p["score"] += a.score; p["correct"] += 1 if a.is_correct else 0
        items.append({
            **question_view(q, names, i + 1), "your_answer": _user_answer_display(q, value), "answered": answered,
            "is_correct": a.is_correct if a else None, "score": a.score if a else None, "correct_answer": _correct_display(q),
            "explanation": q.explanation, "citations": cites, "source_removed": not cites,
            "feedback": {k: v for k, v in (a.feedback or {}).items() if k != "misconception"} if a else {},
            "misconception": (a.feedback or {}).get("misconception") if a else None, "verification": q.verification_status,
        })
    changes: dict = {}
    for h in db.scalars(select(TopicMasteryHistory).where(TopicMasteryHistory.attempt_id == attempt.id).order_by(TopicMasteryHistory.created_at, TopicMasteryHistory.id)):
        c = changes.setdefault(h.topic_id, {"topic_id": str(h.topic_id), "topic_name": names.get(h.topic_id), "before": h.previous_mastery, "after": h.new_mastery, "questions": 0})
        c["after"] = h.new_mastery; c["questions"] += 1
    answered = sum(1 for x in items if x["answered"])
    recs = db.scalars(select(RevisionRecommendation).where(RevisionRecommendation.user_id == attempt.user_id, RevisionRecommendation.course_id == assessment.course_id,
                                                           RevisionRecommendation.status == "open").order_by(RevisionRecommendation.created_at.desc())).all()
    return {
        "attempt_id": str(attempt.id), "assessment_id": str(assessment.id), "mode": assessment.mode, "submitted_at": attempt.submitted_at,
        "score": attempt.score, "max_score": attempt.max_score, "accuracy": (attempt.score / attempt.max_score) if attempt.max_score else 0.0,
        "answered": answered, "total": len(qs), "correct": sum(1 for x in items if x["is_correct"]),
        "overtime_seconds": (attempt.meta or {}).get("overtime_seconds", 0), "timed": assessment.timed,
        "questions": items,
        "topic_performance": [{"topic_id": str(t) if t else None, "topic_name": names.get(t) or "Uncategorised", **v,
                               "accuracy": (v["score"] / v["answered"]) if v["answered"] else None} for t, v in perf.items()],
        "mastery_changes": list(changes.values()),
        "recommendations": [{"id": str(r.id), "kind": r.kind, "reason": r.reason, "topic_id": str(r.topic_id) if r.topic_id else None,
                             "chunk_id": str(r.chunk_id) if r.chunk_id else None, "due_at": r.due_at, "evidence": r.evidence} for r in recs],
        "next_assessment": next_assessment(db, attempt.user_id, assessment.course_id), "estimate_note": ESTIMATE_NOTE,
    }


def analytics(db: Session, user_id, course_id) -> dict:
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id, Topic.parent_id.is_(None)).order_by(Topic.created_at)).all()
    names = {t.id: t.name for t in topics}
    state = latest_mastery(db, user_id, [t.id for t in topics])
    mastery = [{"topic_id": str(t.id), "topic_name": t.name, "mastery": state[t.id].mastery if t.id in state else None,
                "evidence": state[t.id].evidence if t.id in state else 0, "updated_at": state[t.id].updated_at if t.id in state else None,
                "status": "not_assessed" if t.id not in state else "strong" if state[t.id].mastery >= STRONG else "weak" if state[t.id].mastery < WEAK else "developing"}
               for t in topics]
    hist = db.scalars(select(TopicMasteryHistory).where(TopicMasteryHistory.user_id == user_id, TopicMasteryHistory.topic_id.in_(list(names) or [None]))
                      .order_by(TopicMasteryHistory.created_at, TopicMasteryHistory.id)).all()
    timeline = [{"at": h.created_at, "topic_id": str(h.topic_id), "topic_name": names[h.topic_id], "mastery": h.new_mastery, "attempt_id": str(h.attempt_id) if h.attempt_id else None} for h in hist]

    attempts = db.execute(select(AssessmentAttempt, Assessment).join(Assessment, Assessment.id == AssessmentAttempt.assessment_id)
                          .where(AssessmentAttempt.user_id == user_id, Assessment.course_id == course_id, AssessmentAttempt.submitted_at.is_not(None))
                          .order_by(AssessmentAttempt.submitted_at)).all()
    history = [{"attempt_id": str(a.id), "assessment_id": str(s.id), "mode": s.mode, "submitted_at": a.submitted_at, "score": a.score, "max_score": a.max_score,
                "accuracy": (a.score / a.max_score) if a.max_score else 0.0} for a, s in attempts]

    diff: dict = {d: {"answered": 0, "correct": 0} for d in ("easy", "medium", "hard")}
    rows = db.execute(select(Question.difficulty, StudentAnswer.is_correct, StudentAnswer.score).join(StudentAnswer, StudentAnswer.question_id == Question.id)
                      .join(AssessmentAttempt, AssessmentAttempt.id == StudentAnswer.attempt_id).join(Assessment, Assessment.id == AssessmentAttempt.assessment_id)
                      .where(AssessmentAttempt.user_id == user_id, Assessment.course_id == course_id, StudentAnswer.score.is_not(None))).all()
    for d, ok, _ in rows:
        diff[d]["answered"] += 1; diff[d]["correct"] += 1 if ok else 0
    difficulty = [{"difficulty": d, **v, "accuracy": (v["correct"] / v["answered"]) if v["answered"] else None} for d, v in diff.items()]

    today = datetime.now(timezone.utc).date()
    per_day: dict = defaultdict(lambda: {"answers": 0, "attempts": 0})
    for h in hist:
        per_day[h.created_at.date().isoformat()]["answers"] += 1
    for a, _ in attempts:
        per_day[a.submitted_at.date().isoformat()]["attempts"] += 1
    activity = [{"date": (today - timedelta(days=i)).isoformat(), **per_day.get((today - timedelta(days=i)).isoformat(), {"answers": 0, "attempts": 0})} for i in range(13, -1, -1)]

    due = db.scalars(select(RevisionRecommendation).where(RevisionRecommendation.user_id == user_id, RevisionRecommendation.course_id == course_id,
                                                          RevisionRecommendation.status == "open", RevisionRecommendation.kind == "revise_later")
                     .order_by(RevisionRecommendation.due_at)).all()
    return {"mastery": mastery, "timeline": timeline, "assessments": history, "difficulty": difficulty, "activity": activity,
            "strong": [m for m in mastery if m["status"] == "strong"], "weak": [m for m in mastery if m["status"] == "weak"],
            "due_revisions": [{"id": str(r.id), "topic_id": str(r.topic_id) if r.topic_id else None, "topic_name": names.get(r.topic_id), "due_at": r.due_at, "reason": r.reason,
                               "is_due": r.due_at is not None and r.due_at <= datetime.now(timezone.utc) if r.due_at and r.due_at.tzinfo else False} for r in due],
            "note": ESTIMATE_NOTE}
