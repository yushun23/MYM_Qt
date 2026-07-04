"""SQLAlchemy 声明基类。

所有 ORM 模型从此继承。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _new_uuid() -> str:
    """生成 UUID4 字符串。"""
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    """返回当前 UTC 时间（不带时区信息，兼容 SQLite）。"""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """声明基类。"""
    pass


class UUIDMixin:
    """UUID 主键混入。"""

    id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=_new_uuid
    )


class TimestampMixin:
    """创建/更新时间戳混入。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
