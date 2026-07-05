"""Database health check utilities."""

import logging
from dataclasses import dataclass, field

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    """Result of a database health check."""

    is_healthy: bool = True
    integrity_ok: bool = True
    foreign_keys_ok: bool = True
    schema_version: int | None = None
    issues: list[str] = field(default_factory=list)


def check_health(session: Session) -> HealthReport:
    """Run database health checks on the given session.

    Checks:
        - integrity_check (PRAGMA)
        - foreign_key_check (PRAGMA)
        - schema_version from alembic_version table

    Args:
        session: An active SQLAlchemy Session.

    Returns:
        HealthReport with results.
    """
    report = HealthReport()

    # Integrity check
    try:
        result = session.execute(text("PRAGMA integrity_check")).scalar()
        report.integrity_ok = str(result).lower() == "ok"
        if not report.integrity_ok:
            report.issues.append(f"Integrity check failed: {result}")
            report.is_healthy = False
    except Exception as e:
        report.integrity_ok = False
        report.issues.append(f"Integrity check error: {e}")
        report.is_healthy = False

    # Foreign key check
    try:
        fk_results = session.execute(text("PRAGMA foreign_key_check")).fetchall()
        report.foreign_keys_ok = len(fk_results) == 0
        if not report.foreign_keys_ok:
            report.issues.append(f"Foreign key violations: {len(fk_results)} rows")
            report.is_healthy = False
    except Exception as e:
        report.foreign_keys_ok = False
        report.issues.append(f"Foreign key check error: {e}")
        report.is_healthy = False

    # Schema version
    try:
        result = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        report.schema_version = result  # type: ignore[assignment]
    except Exception:
        report.schema_version = None
        report.issues.append("Could not read schema version (table may not exist yet)")

    if report.is_healthy:
        logger.info("Database health check passed. Schema version: %s", report.schema_version)
    else:
        logger.warning("Database health check found issues: %s", report.issues)

    return report
