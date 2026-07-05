"""Database manager: create, open, migrate, and health-check ledger databases."""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from mym.infrastructure.database.base import Base
from mym.infrastructure.database.health import HealthReport, check_health
from mym.infrastructure.database.session import SessionFactory, create_engine_for_ledger

logger = logging.getLogger(__name__)


def get_alembic_config() -> Config:
    """Get Alembic config pointing to our migrations."""
    # Find the alembic.ini relative to the project
    from mym.infrastructure.paths.app_paths import get_app_root

    ini_path = get_app_root() / "alembic.ini"
    if not ini_path.exists():
        raise FileNotFoundError(f"Alembic config not found: {ini_path}")
    return Config(str(ini_path))


class DatabaseManager:
    """Manages the lifecycle of a ledger database: creation, migration, health."""

    def __init__(self, ledger_path: Path) -> None:
        self._ledger_path = ledger_path
        self._engine: Engine | None = None
        self._session_factory: SessionFactory | None = None

    @property
    def ledger_path(self) -> Path:
        return self._ledger_path

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise RuntimeError("Database not opened. Call open() first.")
        return self._engine

    @property
    def session_factory(self) -> SessionFactory:
        if self._session_factory is None:
            raise RuntimeError("Database not opened. Call open() first.")
        return self._session_factory

    def create(self, *, apply_migrations: bool = True) -> None:
        """Create a new ledger database (creates file, runs migrations).

        Raises FileExistsError if the ledger file already exists.
        """
        if self._ledger_path.exists():
            raise FileExistsError(f"Ledger already exists: {self._ledger_path}")

        engine = create_engine_for_ledger(self._ledger_path)

        if apply_migrations:
            self._run_migrations(engine)

        self._engine = engine
        self._session_factory = SessionFactory(engine)
        logger.info("Created new ledger: %s", self._ledger_path)

    def open(self, *, apply_migrations: bool = True) -> None:
        """Open an existing ledger database.

        Raises FileNotFoundError if the ledger file does not exist.
        """
        if not self._ledger_path.exists():
            raise FileNotFoundError(f"Ledger not found: {self._ledger_path}")

        engine = create_engine_for_ledger(self._ledger_path)

        if apply_migrations:
            self._run_migrations(engine)

        self._engine = engine
        self._session_factory = SessionFactory(engine)
        logger.info("Opened ledger: %s", self._ledger_path)

    def close(self) -> None:
        """Close the database engine."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Closed ledger: %s", self._ledger_path)

    def health_check(self) -> HealthReport:
        """Run health checks on the database."""
        session = self.session_factory()
        try:
            return check_health(session)
        finally:
            session.close()

    def new_session(self) -> Session:
        """Create a new short-lived session. Caller must close it."""
        return self.session_factory()

    def _run_migrations(self, engine: Engine) -> None:
        """Run Alembic migrations against the given engine."""
        alembic_cfg = get_alembic_config()
        # Override the sqlalchemy.url for this specific database
        alembic_cfg.set_main_option(
            "sqlalchemy.url", str(engine.url)
        )

        with engine.begin() as connection:
            alembic_cfg.attributes["connection"] = connection
            command.upgrade(alembic_cfg, "head")

        logger.info("Migrations applied successfully for: %s", self._ledger_path)
