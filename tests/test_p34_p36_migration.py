"""Tests for P34-P36 – Legacy scanner and migrator."""

import sqlite3
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.infrastructure.migrations.legacy_scanner import (
    LegacyScanner,
    LegacyDataReader,
    ScanReport,
    LegacyAccount,
    LegacyTransaction,
)
from mym.infrastructure.migrations.legacy_migrator import (
    LegacyMigrator,
    MigrationResult,
)
from mym.infrastructure.database.db_manager import DatabaseManager


@pytest.fixture
def old_db_path():
    """Create a simulated old .mym database with known schema."""
    with tempfile.NamedTemporaryFile(suffix=".mym", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)

    conn = sqlite3.connect(str(tmp_path))
    conn.execute("""
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'asset',
            balance TEXT DEFAULT '0',
            opening_balance TEXT DEFAULT '0',
            is_deleted INTEGER DEFAULT 0,
            is_hidden INTEGER DEFAULT 0,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'expense',
            parent_id INTEGER,
            is_deleted INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            type TEXT DEFAULT 'expense',
            date TEXT NOT NULL,
            amount TEXT DEFAULT '0',
            account_id INTEGER,
            category_id INTEGER,
            description TEXT,
            memo TEXT,
            source TEXT DEFAULT 'manual',
            status TEXT DEFAULT 'posted',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE receivables (
            id INTEGER PRIMARY KEY,
            debtor TEXT,
            amount TEXT DEFAULT '0',
            recovered TEXT DEFAULT '0',
            status TEXT DEFAULT 'pending',
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE receivable_events (
            id INTEGER PRIMARY KEY,
            receivable_id INTEGER,
            type TEXT,
            amount TEXT DEFAULT '0',
            date TEXT,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE budgets (
            id INTEGER PRIMARY KEY,
            year INTEGER,
            month INTEGER,
            status TEXT DEFAULT 'open'
        )
    """)
    conn.execute("""
        CREATE TABLE budget_items (
            id INTEGER PRIMARY KEY,
            budget_id INTEGER,
            category TEXT,
            amount TEXT DEFAULT '0',
            type TEXT DEFAULT 'expense'
        )
    """)
    conn.execute("""
        CREATE TABLE stocks (
            id INTEGER PRIMARY KEY,
            name TEXT,
            broker TEXT,
            initial_capital TEXT DEFAULT '0'
        )
    """)
    conn.execute("""
        CREATE TABLE stock_trades (
            id INTEGER PRIMARY KEY,
            stock_id INTEGER,
            symbol TEXT,
            type TEXT,
            date TEXT,
            shares TEXT DEFAULT '0',
            price TEXT DEFAULT '0',
            amount TEXT DEFAULT '0',
            fee TEXT DEFAULT '0',
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY,
            title TEXT DEFAULT 'Chat',
            provider TEXT DEFAULT 'openai',
            model TEXT DEFAULT 'gpt-4',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            role TEXT DEFAULT 'user',
            content TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE migrations (
            version TEXT PRIMARY KEY
        )
    """)

    # Insert sample data
    conn.execute("INSERT INTO migrations (version) VALUES ('1.0')")
    conn.execute("INSERT INTO settings (key, value) VALUES ('app_version', '0.5.0')")
    conn.execute("INSERT INTO settings (key, value) VALUES ('language', 'zh')")

    conn.execute("INSERT INTO accounts (id, name, type, balance, opening_balance) VALUES (1, '现金', 'asset', '1000', '500')")
    conn.execute("INSERT INTO accounts (id, name, type, balance) VALUES (2, '信用卡', 'liability', '-500')")

    conn.execute("INSERT INTO categories (id, name, type) VALUES (1, '餐饮', 'expense')")
    conn.execute("INSERT INTO categories (id, name, type) VALUES (2, '工资', 'income')")

    conn.execute("INSERT INTO transactions (id, type, date, amount, account_id, category_id, description) VALUES (1, 'expense', '2025-07-01', '100', 1, 1, '午餐')")
    conn.execute("INSERT INTO transactions (id, type, date, amount, account_id, category_id, description) VALUES (2, 'income', '2025-07-01', '5000', 1, 2, '工资')")

    conn.execute("INSERT INTO receivables (id, debtor, amount, recovered, status) VALUES (1, '张三', '500', '200', 'partial')")

    conn.execute("INSERT INTO budgets (id, year, month, status) VALUES (1, 2025, 7, 'open')")
    conn.execute("INSERT INTO budget_items (id, budget_id, category, amount, type) VALUES (1, 1, '餐饮', '1500', 'expense')")

    conn.execute("INSERT INTO stocks (id, name, broker, initial_capital) VALUES (1, '股票账户', '券商A', '100000')")
    conn.execute("INSERT INTO stock_trades (id, stock_id, symbol, type, date, shares, price, amount) VALUES (1, 1, 'AAPL', 'buy', '2025-07-01', '10', '150', '1500')")

    conn.execute("INSERT INTO chat_sessions (id, title) VALUES (1, '旧对话')")
    conn.execute("INSERT INTO chat_messages (id, session_id, role, content) VALUES (1, 1, 'user', '你好')")
    conn.execute("INSERT INTO chat_messages (id, session_id, role, content) VALUES (2, 1, 'assistant', '你好！')")

    conn.commit()
    conn.close()

    yield tmp_path
    tmp_path.unlink(missing_ok=True)


@pytest.fixture
def db_mgr():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    yield mgr
    mgr.close()
    tmp_path.unlink(missing_ok=True)


@pytest.fixture
def session(db_mgr: DatabaseManager) -> Session:
    s = db_mgr.new_session()
    yield s
    s.close()


class TestLegacyScanner:
    """Test the legacy scanner."""

    def test_scan_file(self, old_db_path):
        scanner = LegacyScanner(old_db_path)
        report = scanner.scan()
        assert isinstance(report, ScanReport)
        assert report.file_path == str(old_db_path)

    def test_scan_counts(self, old_db_path):
        scanner = LegacyScanner(old_db_path)
        report = scanner.scan()
        assert report.account_count == 2
        assert report.category_count == 2
        assert report.transaction_count == 2
        assert report.receivable_count == 1
        assert report.budget_period_count == 1
        assert report.stock_account_count == 1
        assert report.stock_trade_count == 1
        assert report.chat_session_count == 1
        assert report.chat_message_count == 2

    def test_scan_version(self, old_db_path):
        scanner = LegacyScanner(old_db_path)
        report = scanner.scan()
        assert report.db_version == "1.0"
        assert report.app_version == "0.5.0"

    def test_scan_is_migratable(self, old_db_path):
        scanner = LegacyScanner(old_db_path)
        report = scanner.scan()
        assert report.is_migratable()

    def test_scan_summary(self, old_db_path):
        scanner = LegacyScanner(old_db_path)
        report = scanner.scan()
        summary = report.summary()
        assert "账户: 2" in summary
        assert "流水: 2" in summary

    def test_scan_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            LegacyScanner("/nonexistent/path.mym")

    def test_estimated_rows(self, old_db_path):
        scanner = LegacyScanner(old_db_path)
        report = scanner.scan()
        assert report.estimated_migration_rows > 0


class TestLegacyDataReader:
    """Test the legacy data reader."""

    def test_read_accounts(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            accounts = reader.read_accounts()
            assert len(accounts) == 2
            assert accounts[0].name == "现金"
            assert accounts[1].name == "信用卡"

    def test_read_categories(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            cats = reader.read_categories()
            assert len(cats) == 2
            assert cats[0].name == "餐饮"

    def test_read_transactions(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            txs = reader.read_transactions()
            assert len(txs) == 2
            assert txs[0].amount == Decimal("100")

    def test_read_receivables(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            recs = reader.read_receivables()
            assert len(recs) == 1
            assert recs[0].debtor == "张三"

    def test_read_budgets(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            budgets = reader.read_budgets()
            assert len(budgets) == 1
            assert budgets[0].year == 2025
            assert len(budgets[0].items) == 1

    def test_read_stocks(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            stocks = reader.read_stock_accounts()
            assert len(stocks) == 1
            trades = reader.read_stock_trades()
            assert len(trades) == 1

    def test_read_chat(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            sessions = reader.read_chat_sessions()
            assert len(sessions) == 1
            assert len(sessions[0].messages) == 2

    def test_read_settings(self, old_db_path):
        with LegacyDataReader(old_db_path) as reader:
            settings = reader.read_settings()
            assert settings.language == "zh"


class TestLegacyMigrator:
    """Test the legacy migrator."""

    def test_scan_and_migrate(self, old_db_path, session):
        migrator = LegacyMigrator(session)
        result = migrator.migrate(str(old_db_path))
        assert result.success
        assert result.accounts_migrated == 2
        assert result.categories_migrated == 2
        assert result.transactions_migrated == 2
        assert result.receivables_migrated == 1
        assert result.budgets_migrated == 1
        assert result.stock_accounts_migrated == 1
        assert result.stock_trades_migrated == 1
        assert result.chat_sessions_migrated == 1
        assert result.chat_messages_migrated == 2

    def test_partial_migration(self, old_db_path, session):
        migrator = LegacyMigrator(session)
        result = migrator.migrate(str(old_db_path), sections=["accounts", "categories"])
        assert result.success
        assert result.accounts_migrated == 2
        assert result.categories_migrated == 2
        assert result.transactions_migrated == 0

    def test_scan_before_migrate(self, old_db_path, session):
        migrator = LegacyMigrator(session)
        report = migrator.scan(str(old_db_path))
        assert report.is_migratable()
        assert report.account_count == 2

    def test_migration_result_summary(self, old_db_path, session):
        migrator = LegacyMigrator(session)
        result = migrator.migrate(str(old_db_path))
        summary = result.summary()
        assert "迁移结果" in summary

    def test_rollback_migration(self, old_db_path, session):
        migrator = LegacyMigrator(session)
        result = migrator.migrate(str(old_db_path))
        assert result.success
        assert result.import_job_id is not None

        success = migrator.rollback_migration(result.import_job_id)
        assert success

    def test_migration_creates_import_job(self, old_db_path, session):
        migrator = LegacyMigrator(session)
        result = migrator.migrate(str(old_db_path))
        assert result.import_job_id is not None
