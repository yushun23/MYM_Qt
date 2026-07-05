"""AuditLog repository."""

from sqlalchemy.orm import Session

from mym.domain.entities.audit import AuditLog


class AuditLogRepository:
    """Repository for AuditLog entity."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, audit: AuditLog) -> None:
        self._session.add(audit)
