"""AuditLog entity – records all critical data mutations."""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mym.infrastructure.database.base import Base, IntegerPrimaryKeyMixin, TimestampMixin


class AuditLog(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Audit trail for every critical data write operation.

    IMPORTANT: Never log passwords, API keys, or full user financial data.
    """

    __tablename__ = "audit_logs"

    action: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    operator: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action='{self.action}', "
            f"entity='{self.entity_type}', source='{self.source}')>"
        )
