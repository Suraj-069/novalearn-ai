"""Shared column helpers."""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Uuid
from sqlalchemy.orm import mapped_column

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def pk():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def created_at():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def json_col():
    """JSON on all backends (JSONB-capable on Postgres via the generic type)."""
    return JSON


def embedding_type():
    """pgvector on PostgreSQL; plain JSON on SQLite so unit tests can run without Postgres."""
    return Vector(get_settings().embedding_dim).with_variant(JSON(), "sqlite")
