import shutil
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_course
from app.core.config import get_settings
from app.database.session import get_db
from app.models.course import Course, Document, ProcessingJob
from app.models.knowledge import Topic
from app.models.user import User
from app.schemas.course import CourseCreate, CourseOut, CourseUpdate

router = APIRouter(prefix="/api/courses", tags=["courses"])


def _course_out(db: Session, course: Course) -> CourseOut:
    docs = db.scalars(select(Document).where(Document.course_id == course.id)).all()
    status_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for d in docs:
        source_counts[d.source_type] = source_counts.get(d.source_type, 0) + 1
        status = d.jobs[0].status if d.jobs else "queued"
        status_counts[status] = status_counts.get(status, 0) + 1
    topics = db.scalar(select(func.count()).select_from(Topic).where(Topic.course_id == course.id)) or 0
    out = CourseOut.model_validate(course)
    out.document_count, out.topic_count = len(docs), topics
    out.status_counts, out.source_counts = status_counts, source_counts
    return out


@router.get("", response_model=list[CourseOut])
def list_courses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    courses = db.scalars(select(Course).where(Course.owner_id == user.id).order_by(Course.created_at.desc())).all()
    return [_course_out(db, c) for c in courses]


@router.post("", response_model=CourseOut, status_code=201)
def create_course(body: CourseCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    course = Course(owner_id=user.id, title=body.title, description=body.description)
    db.add(course)
    db.commit()
    return _course_out(db, course)


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _course_out(db, owned_course(course_id, user, db))


@router.patch("/{course_id}", response_model=CourseOut)
def update_course(course_id: uuid.UUID, body: CourseUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    course = owned_course(course_id, user, db)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "title" and v is not None:
            v = v.strip()
            if not v:
                continue
        setattr(course, k, v)
    db.commit()
    return _course_out(db, course)


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    course = owned_course(course_id, user, db)
    cid = str(course.id)
    db.delete(course)
    db.commit()
    shutil.rmtree(get_settings().upload_root / cid, ignore_errors=True)
