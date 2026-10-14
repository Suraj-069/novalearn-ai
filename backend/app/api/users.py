import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.config import get_settings
from app.database.session import get_db
from app.models.course import Course
from app.models.user import User
from app.schemas.auth import ProfileUpdate, UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.patch("/me", response_model=UserOut)
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "learning_goals" in data:
        data["learning_goals"] = [g.strip()[:80] for g in data["learning_goals"] if g.strip()]
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    return user


@router.get("/me/export")
def export_my_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Data management: a JSON export of the user's profile, courses and document metadata."""
    courses = db.scalars(select(Course).where(Course.owner_id == user.id)).all()
    return {
        "profile": UserOut.model_validate(user).model_dump(mode="json"),
        "courses": [
            {
                "id": str(c.id), "title": c.title, "description": c.description,
                "documents": [
                    {"id": str(d.id), "filename": d.original_filename, "type": d.source_type,
                     "size_bytes": d.size_bytes, "page_count": d.page_count,
                     "slide_count": d.slide_count, "duration_seconds": d.duration_seconds}
                    for d in c.documents
                ],
            }
            for c in courses
        ],
    }


@router.delete("/me", status_code=204)
def delete_my_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Permanently delete the account, all rows owned by it, and its uploaded files."""
    root = get_settings().upload_root
    course_ids = [str(c.id) for c in db.scalars(select(Course).where(Course.owner_id == user.id))]
    db.delete(user)
    db.commit()
    for cid in course_ids:
        shutil.rmtree(root / cid, ignore_errors=True)
