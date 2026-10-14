import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.models._types import created_at, pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(100))
    learning_goals: Mapped[list] = mapped_column(JSON, default=list)
    explanation_style: Mapped[str] = mapped_column(String(30), default="balanced")
    language: Mapped[str] = mapped_column(String(30), default="English")
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at()

    courses = relationship("Course", back_populates="owner", cascade="all, delete-orphan")
