"""P3 tests: Database infrastructure – engine, session, health, migration."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text as sa_text

from mym.infrastructure.database.session import SessionFactory, create_engine_for_ledger


def _temp_db_path() -> Path:
    """Create a temp file path and delete it so db_manager can create it fresh."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        path = Path(f.name)
    path.unlink(missing_ok=True)
    return path


class TestEngineAndSession:
    """Tests for SQLAlchemy engine and session factory."""

    def test_create_engine_temporary_db(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            engine = create_engine_for_ledger(tmp_path)
            assert engine is not None
            engine.dispose()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_session_factory_creates_session(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            engine = create_engine_for_ledger(tmp_path)
            factory = SessionFactory(engine)
            session = factory()
            assert session is not None
            session.close()
            engine.dispose()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_session_can_execute_sql(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            engine = create_engine_for_ledger(tmp_path)
            factory = SessionFactory(engine)
            session = factory()
            result = session.execute(sa_text("SELECT 1")).scalar()
            assert result == 1
            session.close()
            engine.dispose()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_foreign_keys_enabled(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            engine = create_engine_for_ledger(tmp_path)
            factory = SessionFactory(engine)
            session = factory()
            result = session.execute(sa_text("PRAGMA foreign_keys")).scalar()
            assert int(result) == 1
            session.close()
            engine.dispose()
        finally:
            tmp_path.unlink(missing_ok=True)


class TestDatabaseManager:
    """Tests for DatabaseManager (create, open, close, health)."""

    def test_create_new_ledger(self) -> None:
        from mym.infrastructure.database.db_manager import DatabaseManager

        tmp_path = _temp_db_path()
        try:
            mgr = DatabaseManager(tmp_path)
            mgr.create()
            assert tmp_path.exists()
            assert mgr.engine is not None
            mgr.close()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_create_existing_raises(self) -> None:
        from mym.infrastructure.database.db_manager import DatabaseManager

        tmp_path = _temp_db_path()
        try:
            mgr = DatabaseManager(tmp_path)
            mgr.create()
            mgr2 = DatabaseManager(tmp_path)
            with pytest.raises(FileExistsError):
                mgr2.create()
            mgr.close()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_open_existing_ledger(self) -> None:
        from mym.infrastructure.database.db_manager import DatabaseManager

        tmp_path = _temp_db_path()
        try:
            mgr = DatabaseManager(tmp_path)
            mgr.create()
            mgr.close()

            mgr2 = DatabaseManager(tmp_path)
            mgr2.open()
            assert mgr2.engine is not None
            mgr2.close()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_open_nonexistent_raises(self) -> None:
        from mym.infrastructure.database.db_manager import DatabaseManager

        mgr = DatabaseManager(Path("/nonexistent/path/db.sqlite"))
        with pytest.raises(FileNotFoundError):
            mgr.open()

    def test_health_check_on_new_ledger(self) -> None:
        from mym.infrastructure.database.db_manager import DatabaseManager

        tmp_path = _temp_db_path()
        try:
            mgr = DatabaseManager(tmp_path)
            mgr.create()
            report = mgr.health_check()
            assert report.integrity_ok
            assert report.foreign_keys_ok
            mgr.close()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_close_and_reopen(self) -> None:
        from mym.infrastructure.database.db_manager import DatabaseManager

        tmp_path = _temp_db_path()
        try:
            mgr = DatabaseManager(tmp_path)
            mgr.create()
            mgr.close()
            mgr.open()
            report = mgr.health_check()
            assert report.is_healthy
            mgr.close()
        finally:
            tmp_path.unlink(missing_ok=True)


class TestMoneyType:
    """Tests for Money type (Numeric(18,2))."""

    def test_money_is_numeric(self) -> None:
        from sqlalchemy import Numeric

        from mym.infrastructure.database.types_ import Money

        assert isinstance(Money, Numeric)
        assert Money.precision == 18
        assert Money.scale == 2

    def test_account_uses_money_type(self) -> None:
        from sqlalchemy import inspect

        from mym.domain.entities.account import Account

        cols = {c.name: c.type for c in inspect(Account).columns}
        assert "opening_balance" in cols
        assert "current_balance" in cols


class TestBaseModel:
    """Tests for Base model and mixins."""

    def test_base_metadata_has_tables(self) -> None:
        from mym.infrastructure.database.base import Base

        tables = list(Base.metadata.tables.keys())
        assert "accounts" in tables
        assert "categories" in tables
        assert "transactions" in tables
        assert "transaction_lines" in tables
        assert "audit_logs" in tables

    def test_timestamp_mixin_has_columns(self) -> None:
        from sqlalchemy import inspect
        from sqlalchemy.orm import Mapped, mapped_column

        from mym.infrastructure.database.base import Base, TimestampMixin

        class TestModel(Base, TimestampMixin):
            __tablename__ = "_test_timestamp"
            id: Mapped[int] = mapped_column(primary_key=True)

        cols = {c.name for c in inspect(TestModel).columns}
        assert "created_at" in cols
        assert "updated_at" in cols
