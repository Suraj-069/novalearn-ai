import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course
from app.database.session import get_db
from app.models.course import Course, Document
from app.models.evaluation import EvaluationMetric, EvaluationRun
from app.models.knowledge import ContentChunk, Topic
from app.models.user import User
from app.schemas.evaluation import PersonalizationEvaluationIn, RetrievalEvaluationIn
from app.services.evaluation.metrics import run_personalization_evaluation, run_retrieval_evaluation, unavailable_metrics
from app.services.providers.base import ProviderError, ProviderUnavailable
from app.services.providers.embeddings import get_embedding_provider
from app.services.providers.llm import get_llm

router = APIRouter(prefix="/api", tags=["evaluation"])


def _metric_out(m: EvaluationMetric) -> dict:
    return {"name": m.name, "value": m.value, "available": m.available,
            "unavailable_reason": m.unavailable_reason, "sample_size": m.sample_size,
            "details": m.details or {}}


def _run_out(db: Session, run: EvaluationRun) -> dict:
    metrics = db.scalars(select(EvaluationMetric).where(EvaluationMetric.run_id == run.id).order_by(EvaluationMetric.id)).all()
    return {"id": str(run.id), "course_id": str(run.course_id) if run.course_id else None,
            "kind": run.kind, "status": run.status, "config": run.config or {}, "notes": run.notes,
            "created_at": run.created_at, "finished_at": run.finished_at,
            "metrics": [_metric_out(m) for m in metrics]}


def _complete_run(db: Session, run: EvaluationRun, metrics: list[EvaluationMetric]) -> dict:
    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    db.add_all(metrics)
    db.commit()
    return _run_out(db, run)


def _owned_run(run_id: uuid.UUID, user: User, db: Session) -> EvaluationRun:
    run = db.get(EvaluationRun, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(404, "Evaluation run not found.")
    return run


@router.get("/courses/{course_id}/evaluation-sources")
def evaluation_sources(course_id: uuid.UUID, q: str | None = Query(default=None, min_length=1, max_length=120),
                       limit: int = Query(default=100, ge=1, le=300), offset: int = Query(default=0, ge=0),
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    """List real course passages so benchmark labels can cite exact source chunk IDs."""
    owned_course(course_id, user, db)
    query = select(ContentChunk, Document, Topic.name).join(Document, Document.id == ContentChunk.document_id).outerjoin(
        Topic, Topic.id == ContentChunk.topic_id).where(ContentChunk.course_id == course_id)
    count_query = select(func.count(ContentChunk.id)).where(ContentChunk.course_id == course_id)
    if q:
        needle = q.strip()
        if needle:
            query = query.where(ContentChunk.text.ilike(f"%{needle}%"))
            count_query = count_query.where(ContentChunk.text.ilike(f"%{needle}%"))
    rows = db.execute(query.order_by(Document.original_filename, ContentChunk.chunk_index)
                      .offset(offset).limit(limit)).all()
    return {"total": db.scalar(count_query) or 0, "limit": limit, "offset": offset,
            "items": [{"chunk_id": str(c.id), "filename": d.original_filename, "source_type": c.source_type,
                       "page": c.page_number, "slide": c.slide_number,
                       "start_seconds": c.start_seconds, "end_seconds": c.end_seconds,
                       "figure_ref": c.figure_ref, "ai_generated": c.is_generated_description,
                       "topic_name": topic_name, "excerpt": c.text[:360]}
                      for c, d, topic_name in rows]}


@router.get("/courses/{course_id}/evaluations")
def list_evaluations(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_course(course_id, user, db)
    runs = db.scalars(select(EvaluationRun).where(EvaluationRun.course_id == course_id, EvaluationRun.user_id == user.id)
                      .order_by(EvaluationRun.created_at.desc()).limit(50)).all()
    return [_run_out(db, run) for run in runs]


@router.post("/courses/{course_id}/evaluations/retrieval", status_code=201)
def create_retrieval_evaluation(course_id: uuid.UUID, body: RetrievalEvaluationIn,
                                user: User = Depends(current_user), db: Session = Depends(get_db)):
    course = owned_course(course_id, user, db)
    all_ids = {chunk_id for case in body.cases for chunk_id in case.relevant_chunk_ids}
    if all_ids:
        valid_ids = set(db.scalars(select(ContentChunk.id).where(ContentChunk.course_id == course_id,
                                                                   ContentChunk.id.in_(all_ids))))
        if valid_ids != all_ids:
            raise HTTPException(422, "Every labeled source chunk must belong to this course.")
    run = EvaluationRun(user_id=user.id, course_id=course.id, kind="retrieval", status="running",
                        config={"case_count": len(body.cases), "metric_method": "nova-rag-eval-v1"})
    db.add(run)
    db.flush()
    try:
        embedder = get_embedding_provider()
        try:
            llm = get_llm()
        except ProviderUnavailable:
            llm = None
        model_name = getattr(llm, "name", None)
        run.config = {**(run.config or {}), "answer_model": model_name, "judge_model": model_name}
        metrics = run_retrieval_evaluation(db, run=run, user=user, course=course, body=body,
                                           embedder=embedder, llm=llm)
        return _complete_run(db, run, metrics)
    except (ProviderError, ProviderUnavailable) as exc:
        run.status = "failed"
        run.notes = f"Retrieval could not run: {exc}"
        run.finished_at = datetime.now(timezone.utc)
        db.add_all(unavailable_metrics(run, ["context_precision", "context_recall", "faithfulness",
                                             "answer_relevancy", "refusal_accuracy"], str(exc)))
        db.commit()
        return _run_out(db, run)


@router.post("/courses/{course_id}/evaluations/personalization", status_code=201)
def create_personalization_evaluation(course_id: uuid.UUID, body: PersonalizationEvaluationIn,
                                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    course = owned_course(course_id, user, db)
    run = EvaluationRun(user_id=user.id, course_id=course.id, kind="personalization", status="running",
                        config={"sessions": body.sessions, "questions_per_session": body.questions_per_session,
                                "runs": body.runs, "profile_count": len(body.profiles), "seed": body.seed})
    db.add(run)
    db.flush()
    metrics = run_personalization_evaluation(db, run=run, course=course, body=body)
    return _complete_run(db, run, metrics)


@router.get("/evaluations/{run_id}")
def get_evaluation(run_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _run_out(db, _owned_run(run_id, user, db))
