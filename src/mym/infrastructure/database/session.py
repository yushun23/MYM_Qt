"""SQLAlchemy Engine and Session factory for ledger SQLite files."""

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


def create_engine_for_ledger(ledger_path: Path, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy Engine for a specific ledger SQLite file.

    Args:
        ledger_path: Path to the SQLite file.
        echo: If True, log all SQL statements.

    Returns:
        Configured SQLAlchemy Engine.
    """
    db_url = f"sqlite:///{ledger_path}"

    engine = create_engine(
        db_url,
        echo=echo,
        connect_args={
            "check_same_thread": False,
        },
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        """Enable foreign keys on every new connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.close()

    logger.debug("Engine created for: %s", ledger_path)
    return engine


class SessionFactory:
    """Factory that creates short-lived SQLAlchemy Sessions.

    Each thread/background task should create its own Session via __call__().
    Sessions are not shared across threads.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._maker = sessionmaker(bind=engine, expire_on_commit=False)

    def __call__(self) -> Session:
        """Create a new Session. Caller is responsible for closing it."""
        return self._maker()

    @property
    def engine(self) -> Engine:
        return self._engine
