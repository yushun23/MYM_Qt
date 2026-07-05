"""SQLAlchemy declarative base with common columns and conventions."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.sqlite import CHAR as SQLiteChar
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class TimestampMixin:
    """Mixin adding created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class UUIDPrimaryKeyMixin:
    """Mixin using UUID string as primary key."""

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )


class IntegerPrimaryKeyMixin:
    """Mixin using auto-increment integer as primary key."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


class SoftDeleteMixin:
    """Mixin for soft-delete support."""

    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ArchivableMixin:
    """Mixin for archivable entities."""

    is_archived: Mapped[bool] = mapped_column(default=False, nullable=False)
