"""ImportJob, ImportIssue, and LegacyIdMap entities."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import ImportIssueSeverity, ImportStatus
from mym.infrastructure.database.base import Base, IntegerPrimaryKeyMixin, TimestampMixin


class ImportJob(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Records an import operation (CSV, broker settlement, migration, etc.)."""

    __tablename__ = "import_jobs"

    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    import_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(String(20), default=ImportStatus.PENDING, nullable=False)
    total_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    success_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    skipped_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    issues: Mapped[list["ImportIssue"]] = relationship(
        "ImportIssue", back_populates="import_job",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ImportJob(id={self.id}, type='{self.import_type}', status={self.status})>"


class ImportIssue(Base, IntegerPrimaryKeyMixin):
    """An issue encountered during import."""

    __tablename__ = "import_issues"

    import_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int | None] = mapped_column(nullable=True)
    severity: Mapped[ImportIssueSeverity] = mapped_column(String(20), default=ImportIssueSeverity.WARNING, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    import_job: Mapped["ImportJob"] = relationship("ImportJob", back_populates="issues")

    def __repr__(self) -> str:
        return f"<ImportIssue(id={self.id}, severity={self.severity})>"


class LegacyIdMap(Base, IntegerPrimaryKeyMixin):
    """Maps old system IDs (table + PK) to new entity IDs."""

    __tablename__ = "legacy_id_map"

    import_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("import_jobs.id"), nullable=False
    )
    legacy_table: Mapped[str] = mapped_column(String(100), nullable=False)
    legacy_pk: Mapped[str] = mapped_column(String(100), nullable=False)
    new_table: Mapped[str] = mapped_column(String(100), nullable=False)
    new_id: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"<LegacyIdMap({self.legacy_table}.{self.legacy_pk} → {self.new_table}.{self.new_id})>"
