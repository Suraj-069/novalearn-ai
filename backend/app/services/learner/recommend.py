"""Rule-based recommendations. Every one stores the numbers that triggered it, so it is traceable to real performance."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.assessment import AssessmentQuestion, Assessment, AssessmentAttempt, Question, QuestionSource, StudentAnswer
from app.models.knowledge import ContentChunk, Topic, TopicPrerequisite
from app.models.learner import RevisionRecommendation
from app.services.learner.mastery import latest_mastery

WEAK, STRONG = 0.40, 0.75
MAX_RECS = 10


def review_interval_days(mastery: float) -> int:
    """Spaced repetition: the stronger the estimate, the longer until the topic is due again."""
    return 1 if mastery < 0.5 else 2 if mastery < 0.65 else 4 if mastery < 0.8 else 7 if mastery < 0.9 else 14


def _recent_miss(db: Session, user_id, topic_id) -> tuple[Question | None, ContentChunk | None]:
    row = db.execute(
        select(Question, StudentAnswer).join(StudentAnswer, StudentAnswer.question_id == Question.id)
        .join(AssessmentAttempt, AssessmentAttempt.id == StudentAnswer.attempt_id)
        .where(AssessmentAttempt.user_id == user_id, Question.topic_id == topic_id, StudentAnswer.is_correct.is_(False),
               StudentAnswer.score.is_not(None))
        .order_by(AssessmentAttempt.submitted_at.desc()).limit(1)
    ).first()
    if not row:
        return None, None
    chunk = db.scalars(select(ContentChunk).join(QuestionSource, QuestionSource.chunk_id == ContentChunk.id)
                       .where(QuestionSource.question_id == row[0].id).limit(1)).first()
    return row[0], chunk


def generate_recommendations(db: Session, user_id, course_id, now: datetime | None = None) -> list[RevisionRecommendation]:
    now = now or datetime.now(timezone.utc)
    for old in db.scalars(select(RevisionRecommendation).where(RevisionRecommendation.user_id == user_id,
                                                                RevisionRecommendation.course_id == course_id,
                                                                RevisionRecommendation.status == "open")):
        old.status = "superseded"

    topics = db.scalars(select(Topic).where(Topic.course_id == course_id, Topic.parent_id.is_(None)).order_by(Topic.created_at)).all()
    names = {t.id: t.name for t in topics}
    mastery = latest_mastery(db, user_id, [t.id for t in topics])
    prereqs: dict[uuid.UUID, list[uuid.UUID]] = {}
    for p in db.scalars(select(TopicPrerequisite).where(TopicPrerequisite.topic_id.in_(list(names) or [uuid.uuid4()]))):
        if p.prerequisite_id in names:
            prereqs.setdefault(p.topic_id, []).append(p.prerequisite_id)

    recs: list[tuple[int, RevisionRecommendation]] = []

    def add(priority, topic_id, kind, reason, evidence, chunk_id=None, due=None):
        recs.append((priority, RevisionRecommendation(user_id=user_id, course_id=course_id, topic_id=topic_id, chunk_id=chunk_id,
                                                       kind=kind, reason=reason, evidence=evidence, due_at=due, status="open")))

    for t in topics:
        st = mastery.get(t.id)
        if st is None:
            if mastery:  # the student has quizzed other topics but never this one
                add(5, t.id, "assess_topic", f"You haven't been assessed on {t.name} yet, so nothing is assumed about it. A short quiz will establish a starting point.",
                    {"topic": t.name, "evidence_count": 0})
            continue
        m = st.mastery
        ev = {"topic": t.name, "mastery_estimate": round(m, 3), "evidence_count": st.evidence}
        if m < WEAK:
            weak_pre = [(pid, mastery.get(pid)) for pid in prereqs.get(t.id, []) if mastery.get(pid) is None or mastery[pid].mastery < 0.5]
            for pid, pst in weak_pre:
                add(0, pid, "revisit_prerequisite",
                    f"Your estimate for {t.name} is {m:.0%}. Its prerequisite {names[pid]} is "
                    f"{'not assessed yet' if pst is None else f'{pst.mastery:.0%}'}, so revisit {names[pid]} first.",
                    {**ev, "prerequisite": names[pid], "prerequisite_mastery": None if pst is None else round(pst.mastery, 3)})
            q, chunk = _recent_miss(db, user_id, t.id)
            if chunk is not None:
                kind = "review_figure" if chunk.figure_ref else "read_source"
                what = "this figure" if chunk.figure_ref else "this passage"
                add(1, t.id, kind, f"You missed a question on {t.name} (estimate {m:.0%}). Re-read {what} from your material.",
                    {**ev, "missed_question_id": str(q.id)}, chunk_id=chunk.id)
            add(2, t.id, "easier_practice", f"Estimate for {t.name} is {m:.0%}. Try easier practice questions before moving on.", {**ev, "suggested_difficulty": "easy"})
        elif m < STRONG:
            add(3, t.id, "practice", f"Estimate for {t.name} is {m:.0%}. More practice at medium difficulty should firm it up.", {**ev, "suggested_difficulty": "medium"})
        else:
            days = review_interval_days(m)
            add(4, t.id, "challenge", f"Estimate for {t.name} is {m:.0%}. Try harder, recall-style questions.", {**ev, "suggested_difficulty": "hard"})
            add(6, t.id, "revise_later", f"Revise {t.name} again in {days} day{'s' if days != 1 else ''} to keep it fresh (estimate {m:.0%}).",
                {**ev, "interval_days": days}, due=now + timedelta(days=days))

    recs.sort(key=lambda x: x[0])
    out = [r for _, r in recs[:MAX_RECS]]
    db.add_all(out)
    db.flush()
    return out
