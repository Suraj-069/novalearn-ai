from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database.session import get_db
from app.models.assessment import Assessment, AssessmentAttempt
from app.models.course import Course, Document, ProcessingJob
from app.models.knowledge import Topic
from app.models.learner import RevisionRecommendation, TopicMasteryHistory
from app.models.user import User
from app.schemas.dashboard import (
    ActivityOut, AssessmentSummaryOut, DashboardOut, RecommendationOut, TopicMasteryOut, UpcomingRevisionOut,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

WEAK_THRESHOLD = 0.5  # mastery estimate below this is shown as "needs attention"


@router.get("", response_model=DashboardOut)
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    course_ids = list(db.scalars(select(Course.id).where(Course.owner_id == user.id)))
    docs = db.scalars(select(Document).where(Document.course_id.in_(course_ids))).all() if course_ids else []
    topic_count = db.scalar(select(func.count()).select_from(Topic).where(Topic.course_id.in_(course_ids))) if course_ids else 0

    # Current mastery = most recent history row per topic (real data only).
    latest = (
        select(TopicMasteryHistory.topic_id, func.max(TopicMasteryHistory.created_at).label("t"))
        .where(TopicMasteryHistory.user_id == user.id)
        .group_by(TopicMasteryHistory.topic_id)
        .subquery()
    )
    rows = db.execute(
        select(TopicMasteryHistory, Topic)
        .join(latest, (TopicMasteryHistory.topic_id == latest.c.topic_id) & (TopicMasteryHistory.created_at == latest.c.t))
        .join(Topic, Topic.id == TopicMasteryHistory.topic_id)
        .where(TopicMasteryHistory.user_id == user.id)
    ).all()
    mastery = [
        TopicMasteryOut(topic_id=t.id, topic_name=t.name, course_id=t.course_id, mastery=h.new_mastery, updated_at=h.created_at)
        for h, t in rows
    ]
    mastery.sort(key=lambda m: m.mastery)
    weak = [m for m in mastery if m.mastery < WEAK_THRESHOLD][:5]

    activity: list[ActivityOut] = [
        ActivityOut(kind="upload", label=f"Uploaded {d.original_filename}", course_id=d.course_id, at=d.created_at)
        for d in docs
    ]
    attempts = db.scalars(
        select(AssessmentAttempt).where(AssessmentAttempt.user_id == user.id, AssessmentAttempt.submitted_at.is_not(None))
        .order_by(AssessmentAttempt.submitted_at.desc()).limit(10)
    ).all()
    assessments_out: list[AssessmentSummaryOut] = []
    for a in attempts:
        assessment = db.get(Assessment, a.assessment_id)
        cid = assessment.course_id
        activity.append(ActivityOut(kind="assessment", label="Completed an assessment", course_id=cid, at=a.submitted_at))
        assessments_out.append(AssessmentSummaryOut(
            attempt_id=a.id, course_id=cid, score=a.score or 0, max_score=a.max_score or 0, submitted_at=a.submitted_at,
        ))
    activity.sort(key=lambda a: a.at, reverse=True)

    recs = db.scalars(
        select(RevisionRecommendation).where(RevisionRecommendation.user_id == user.id, RevisionRecommendation.status == "open")
        .order_by(RevisionRecommendation.created_at.desc()).limit(5)
    ).all()

    from app.models._types import utcnow
    now = utcnow()
    revs = db.scalars(select(RevisionRecommendation).where(RevisionRecommendation.user_id == user.id, RevisionRecommendation.status == "open",
                                                           RevisionRecommendation.kind == "revise_later", RevisionRecommendation.due_at.is_not(None))
                      .order_by(RevisionRecommendation.due_at).limit(5)).all()
    topic_by_id = {t.id: t.name for t in db.scalars(select(Topic).where(Topic.id.in_([r.topic_id for r in revs if r.topic_id])))} if revs else {}
    upcoming = []
    for r in revs:
        due = r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=timezone.utc)
        upcoming.append(UpcomingRevisionOut(id=r.id, course_id=r.course_id, topic_name=topic_by_id.get(r.topic_id), due_at=due, is_due=due <= now, reason=r.reason))

    indexed = 0
    for d in docs:
        if d.jobs and d.jobs[0].status == "indexed":
            indexed += 1

    return DashboardOut(
        course_count=len(course_ids), document_count=len(docs), indexed_document_count=indexed, topic_count=topic_count or 0,
        mastery=mastery, weak_topics=weak, recent_activity=activity[:8],
        recommendations=[RecommendationOut(id=r.id, course_id=r.course_id, topic_id=r.topic_id, kind=r.kind, reason=r.reason) for r in recs],
        recent_assessments=assessments_out[:5], upcoming_revisions=upcoming,
    )
