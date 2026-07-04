"""导入运行记录模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mym2.db.base import Base, UUIDMixin, _utcnow


class ImportRun(Base, UUIDMixin):
    """导入运行记录 — 记录每次数据导入/迁移。"""

    __tablename__ = 'import_runs'

    source: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default='dry_run', nullable=False,
        comment='dry_run/completed/failed/rolled_back'
    )
    rows_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
