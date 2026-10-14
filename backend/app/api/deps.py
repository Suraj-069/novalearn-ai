import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.course import Course, Document
from app.models.user import User

bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status_code=401, detail="Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    sub = decode_access_token(creds.credentials)
    if sub is None:
        raise unauthorized
    try:
        user = db.get(User, uuid.UUID(sub))
    except ValueError:
        raise unauthorized
    if user is None:
        raise unauthorized
    return user


def owned_course(course_id: uuid.UUID, user: User, db: Session) -> Course:
    """Return the course only if the user owns it. 404 (not 403) so IDs can't be probed."""
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Course not found.")
    return course


def owned_document(document_id: uuid.UUID, user: User, db: Session) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.course.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc
