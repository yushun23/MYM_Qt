"""审计事件模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mym2.db.base import Base, UUIDMixin, _utcnow


class AuditEvent(Base, UUIDMixin):
    """审计事件 — 记录所有账本写入操作。"""

    __tablename__ = 'audit_events'

    action: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    changes_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
