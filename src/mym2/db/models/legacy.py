"""旧数据归档与 ID 映射模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mym2.db.base import Base, UUIDMixin, _utcnow


class LegacyIdMap(Base, UUIDMixin):
    """旧 ID → 新 ID 映射 — 防止重复导入。"""

    __tablename__ = 'legacy_id_map'
    __table_args__ = (
        Index('ix_legacy_lookup', 'import_run_id', 'source_table', 'legacy_id'),
    )

    import_run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey('import_runs.id'), nullable=False
    )
    source_table: Mapped[str] = mapped_column(String(100), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    new_table: Mapped[str] = mapped_column(String(100), nullable=False)
    new_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )


class LegacyArchiveRecord(Base, UUIDMixin):
    """旧数据归档 — 保存脱敏后的原始数据。"""

    __tablename__ = 'legacy_archive_records'

    import_run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey('import_runs.id'), nullable=False
    )
    source_table: Mapped[str] = mapped_column(String(100), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False, comment='脱敏 JSON')
    summary: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
