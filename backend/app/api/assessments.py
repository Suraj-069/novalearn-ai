import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course
from app.database.session import get_db
from app.models.assessment import Assessment, AssessmentAttempt
from app.models.knowledge import Topic
from app.models.learner import RevisionRecommendation
from app.models.user import User
from app.schemas.assessment import AssessmentCreate, SubmitIn
from app.schemas.study import StudyPlanIn
from app.services.assessment import results
from app.services.assessment.service import (AssessmentError, assessment_questions, create_assessment, start_attempt, submit_attempt)
from app.services.learner.mastery import latest_mastery
from app.services.learner.schedule import build_study_plan
from app.services.providers.base import ProviderError, ProviderUnavailable
from app.services.providers.embeddings import get_embedding_provider
from app.services.providers.llm import get_llm

router = APIRouter(prefix="/api", tags=["assessments"])


@router.post("/courses/{course_id}/study-plan")
def study_plan(course_id: uuid.UUID, body: StudyPlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    topics = db.scalars(select(Topic).where(Topic.course_id == course_id, Topic.parent_id.is_(None)).order_by(Topic.name)).all()
    states = latest_mastery(db, user.id, [topic.id for topic in topics])
    rows = [{"id": str(topic.id), "name": topic.name,
             "mastery": states[topic.id].mastery if topic.id in states else None} for topic in topics]
    try:
        return build_study_plan(rows, today=date.today(), exam_date=body.exam_date,
                                hours_per_day=body.hours_per_day)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def _owned_assessment(aid: uuid.UUID, user: User, db: Session) -> Assessment:
    a = db.get(Assessment, aid)
    if a is None or a.user_id != user.id:
        raise HTTPException(404, "Assessment not found.")
    return a


def _owned_attempt(tid: uuid.UUID, user: User, db: Session) -> tuple[AssessmentAttempt, Assessment]:
    att = db.get(AssessmentAttempt, tid)
    if att is None or att.user_id != user.id:
        raise HTTPException(404, "Attempt not found.")
    return att, db.get(Assessment, att.assessment_id)


def _assessment_out(a: Assessment, qs, names) -> dict:
    return {"id": str(a.id), "course_id": str(a.course_id), "mode": a.mode, "timed": a.timed, "time_limit_seconds": a.time_limit_seconds,
            "created_at": a.created_at, "generation": a.config.get("generation"),
            "questions": [results.question_view(q, names, i + 1) for i, q in enumerate(qs)]}


@router.post("/courses/{course_id}/assessments", status_code=201)
def create(course_id: uuid.UUID, body: AssessmentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    for tid in body.topic_ids:
        t = db.get(Topic, tid)
        if t is None or t.course_id != course_id:
            raise HTTPException(400, "A selected topic isn't in this course.")
    try:
        try:
            llm = get_llm()
        except ProviderUnavailable:
            llm = None
        a, qs, report = create_assessment(db, user=user, course_id=course_id, mode=body.mode, topic_ids=body.topic_ids, n=body.num_questions, difficulty=body.difficulty,
                                          types=body.types, timed=body.timed, minutes=body.time_limit_minutes, embedder=get_embedding_provider(), llm=llm, seed=body.seed)
    except AssessmentError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    except ProviderError as e:
        db.rollback()
        raise HTTPException(502, str(e))
    db.commit()
    out = _assessment_out(a, qs, results.topic_names(db, course_id))
    out.update(warnings=report.warnings, rejected_candidates=len(report.rejected))
    return out


@router.get("/courses/{course_id}/assessments")
def list_assessments(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    rows = db.scalars(select(Assessment).where(Assessment.course_id == course_id, Assessment.user_id == user.id).order_by(Assessment.created_at.desc()).limit(50)).all()
    out = []
    for a in rows:
        att = db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.assessment_id == a.id).order_by(AssessmentAttempt.started_at.desc())).first()
        n = len(assessment_questions(db, a.id))
        out.append({"id": str(a.id), "mode": a.mode, "timed": a.timed, "question_count": n, "created_at": a.created_at,
                    "status": "not_started" if att is None else "completed" if att.submitted_at else "in_progress", "attempt_id": str(att.id) if att else None,
                    "score": att.score if att and att.submitted_at else None, "max_score": att.max_score if att and att.submitted_at else None})
    return out


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _owned_assessment(assessment_id, user, db)
    return _assessment_out(a, assessment_questions(db, a.id), results.topic_names(db, a.course_id))


@router.post("/assessments/{assessment_id}/attempts", status_code=201)
def begin(assessment_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _owned_assessment(assessment_id, user, db)
    try:
        att = start_attempt(db, user, a)
    except AssessmentError as e:
        raise HTTPException(409, str(e))
    db.commit()
    out = _assessment_out(a, assessment_questions(db, a.id), results.topic_names(db, a.course_id))
    return {"attempt_id": str(att.id), "started_at": att.started_at, **out}


@router.post("/attempts/{attempt_id}/submit")
def submit(attempt_id: uuid.UUID, body: SubmitIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    att, a = _owned_attempt(attempt_id, user, db)
    qs = {q.id: q for q in assessment_questions(db, a.id)}
    for qid, val in body.answers.items():
        q = qs.get(qid)
        if q is not None and q.question_type == "mcq" and val not in (None, "") and val not in {o["id"] for o in q.options}:
            raise HTTPException(422, "One of your multiple-choice answers isn't a valid option.")
        if val is not None and len(val) > 2000:
            raise HTTPException(422, "An answer is too long.")
    try:
        has_answered_short_answer = any(qs.get(qid) is not None and qs[qid].question_type == "short_answer"
                                        and isinstance(val, str) and bool(val.strip())
                                        for qid, val in body.answers.items())
        grading_llm = None
        if has_answered_short_answer:
            try:
                grading_llm = get_llm()
            except ProviderUnavailable:
                grading_llm = None
        submit_attempt(db, user, att, a, dict(body.answers), grading_llm=grading_llm)
    except AssessmentError as e:
        db.rollback()
        raise HTTPException(409, str(e))
    db.commit()
    return results.attempt_result(db, att, a)


@router.get("/attempts/{attempt_id}")
def get_result(attempt_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    att, a = _owned_attempt(attempt_id, user, db)
    if att.submitted_at is None:
        raise HTTPException(409, "This attempt hasn't been submitted yet.")
    return results.attempt_result(db, att, a)


@router.get("/courses/{course_id}/attempts")
def attempts(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    return results.analytics(db, user.id, course_id)["assessments"]


@router.get("/courses/{course_id}/analytics")
def course_analytics(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    return results.analytics(db, user.id, course_id)


@router.get("/courses/{course_id}/next-assessment")
def next_assessment(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    return results.next_assessment(db, user.id, course_id)


@router.get("/courses/{course_id}/recommendations")
def recommendations(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    rows = db.scalars(select(RevisionRecommendation).where(RevisionRecommendation.user_id == user.id, RevisionRecommendation.course_id == course_id,
                                                           RevisionRecommendation.status == "open").order_by(RevisionRecommendation.created_at.desc())).all()
    return [{"id": str(r.id), "kind": r.kind, "reason": r.reason, "topic_id": str(r.topic_id) if r.topic_id else None,
             "chunk_id": str(r.chunk_id) if r.chunk_id else None, "due_at": r.due_at, "evidence": r.evidence} for r in rows]


@router.post("/recommendations/{rec_id}/dismiss", status_code=204)
def dismiss(rec_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = db.get(RevisionRecommendation, rec_id)
    if r is None or r.user_id != user.id:
        raise HTTPException(404, "Recommendation not found.")
    r.status = "dismissed"
    db.commit()
