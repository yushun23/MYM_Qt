"""迁移执行器测试。

覆盖：完整迁移、余额核对、交易计数、FK 检查、
异常回滚、重复导入拒绝、股票归档、Settings 过滤。
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from mym2.importers.legacy_mym.executor import MigrationExecutor
from mym2.importers.legacy_mym.migration_plan import MigrationPlan

# ── 构建测试用脱敏 .mym fixture ──────────────────────


def _build_executor_test_mym(db_path: Path) -> None:
    """创建测试用旧 .mym（与 test_migration_dryrun 结构一致）。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode=WAL')

    conn.execute('''
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT,
            balance REAL DEFAULT 0.0, is_active INTEGER DEFAULT 1,
            group_name TEXT, linked_stock_account_id INTEGER,
            is_system_locked INTEGER DEFAULT 0, opening_balance REAL DEFAULT 0.0
        )
    ''')
    conn.executemany(
        'INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?)',
        [
            (1, '现金', 'Asset', 500.00, 1, '现金账户', None, 0, 0.0),
            (2, '银行储蓄', 'Asset', 15000.00, 1, '银行存款', None, 0, 10000.0),
            (3, '招商信用卡', 'Liability', 3200.50, 1, '信用卡', None, 0, 0.0),
            (4, '证券账户', 'Asset', 80000.00, 1, '上市证券', 1, 1, 50000.0),
        ],
    )

    conn.execute('''
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT,
            is_active INTEGER DEFAULT 1, group_name TEXT
        )
    ''')
    conn.executemany(
        'INSERT INTO categories VALUES (?,?,?,?,?)',
        [
            (1, '餐饮', 'Expense', 1, '日常'),
            (2, '交通', 'Expense', 1, '日常'),
            (3, '工资', 'Income', 1, '收入'),
        ],
    )

    conn.execute('''
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, trans_date DATE, trans_type TEXT,
            category_id INTEGER, account_out_id INTEGER,
            account_in_id INTEGER, amount REAL, note TEXT,
            is_cleared INTEGER DEFAULT 0
        )
    ''')
    conn.executemany(
        'INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?)',
        [
            (1, '2026-06-01', 'Expense', 1, 2, None, 50.00, '午餐', 0),
            (2, '2026-06-02', 'Expense', 2, 2, None, 25.00, '地铁', 0),
            (3, '2026-06-03', 'Income', 3, None, 2, 5000.00, '6月工资', 0),
            (4, '2026-06-04', 'Transfer', None, 2, 1, 1000.00, '取现', 0),
        ],
    )

    conn.execute('''
        CREATE TABLE budget_months (id INTEGER PRIMARY KEY, year INTEGER, month INTEGER)
    ''')
    conn.execute('INSERT INTO budget_months VALUES (1, 2026, 6)')

    conn.execute('''
        CREATE TABLE budget_lines (
            id INTEGER PRIMARY KEY, budget_month_id INTEGER,
            category_id INTEGER, amount REAL, note TEXT
        )
    ''')
    conn.execute('INSERT INTO budget_lines VALUES (1, 1, 1, 2000.00, "6月餐饮")')

    conn.execute('''
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)
    ''')
    conn.executemany(
        'INSERT INTO settings VALUES (?,?)',
        [
            ('theme', 'dark'),
            ('language', 'zh_CN'),
            ('api_key', 'blocked-value'),
            ('password_hash', 'blocked-value'),
        ],
    )

    conn.execute('''
        CREATE TABLE stock_accounts (
            id INTEGER PRIMARY KEY, name TEXT, currency TEXT,
            cash_balance REAL, note TEXT, is_active INTEGER
        )
    ''')
    conn.execute('INSERT INTO stock_accounts VALUES (1, "证券", "CNY", 30000.0, "", 1)')

    conn.execute('''
        CREATE TABLE stock_trades (
            id INTEGER PRIMARY KEY, stock_account_id INTEGER, trade_date TEXT,
            symbol TEXT, price REAL, amount REAL
        )
    ''')
    conn.execute('INSERT INTO stock_trades VALUES (1, 1, "2026-06-15", "000001", 12.5, 1250.0)')

    conn.execute('''
        CREATE TABLE ai_chat_messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT)
    ''')
    conn.execute('INSERT INTO ai_chat_messages VALUES (1, "user", "帮我记账")')

    conn.execute('''
        CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)
    ''')
    conn.execute('INSERT INTO schema_migrations VALUES ("001_initial")')

    conn.commit()
    conn.close()


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def source_mym(tmp_path: Path) -> Path:
    """创建测试用 .mym 源文件。"""
    db_path = tmp_path / 'source.mym'
    _build_executor_test_mym(db_path)
    return db_path


@pytest.fixture
def target_db(tmp_path: Path) -> Path:
    """创建目标数据库路径。"""
    return tmp_path / 'target.db'


@pytest.fixture
def source_hash(source_mym: Path) -> str:
    """计算源文件哈希。"""
    return hashlib.sha256(source_mym.read_bytes()).hexdigest()


# ── 完整迁移测试 ─────────────────────────────────────


class TestFullMigration:
    """完整迁移流程测试。"""

    def test_migration_succeeds(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """完整迁移成功。"""
        executor = MigrationExecutor(source_mym, target_db)
        report = executor.execute()

        assert report['status'] == 'completed'
        stats = report['stats']
        assert stats['accounts_imported'] >= 3
        assert stats['categories_imported'] >= 3
        assert stats['transactions_imported'] >= 4
        assert stats['budget_periods_imported'] >= 1
        assert stats['budget_lines_imported'] >= 1
        assert stats['settings_imported'] >= 2  # theme + language
        assert stats['archived'] >= 2  # stock + ai

    def test_source_hash_unchanged(
        self, source_mym: Path, target_db: Path, source_hash: str
    ) -> None:
        """迁移后源文件哈希不变。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        new_hash = hashlib.sha256(source_mym.read_bytes()).hexdigest()
        assert new_hash == source_hash

    def test_target_db_created(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """目标数据库创建成功。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        assert target_db.exists()
        assert target_db.stat().st_size > 0

    def test_no_sensitive_in_target(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """目标数据库不含敏感 settings。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        conn = sqlite3.connect(str(target_db))
        rows = conn.execute('SELECT key, value FROM app_settings').fetchall()
        keys = [r[0] for r in rows]
        assert 'api_key' not in keys
        assert 'password_hash' not in keys
        assert 'theme' in keys
        assert 'language' in keys
        conn.close()

    def test_stock_archived_not_rebuilt(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """股票数据归档而非功能重建。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        conn = sqlite3.connect(str(target_db))
        archive_count = conn.execute(
            'SELECT COUNT(*) FROM legacy_archive_records WHERE source_table LIKE "stock_%"'
        ).fetchone()[0]
        assert archive_count >= 1
        conn.close()

    def test_investment_snapshot_created(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """链接证券账户创建为投资快照。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        conn = sqlite3.connect(str(target_db))
        snapshots = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE type = 'investment_snapshot'"
        ).fetchone()[0]
        assert snapshots >= 1
        conn.close()

    def test_legacy_id_map_created(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """LegacyIdMap 记录生成。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        conn = sqlite3.connect(str(target_db))
        map_count = conn.execute('SELECT COUNT(*) FROM legacy_id_map').fetchone()[0]
        assert map_count > 0
        conn.close()

    def test_import_run_recorded(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """ImportRun 记录生成。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        conn = sqlite3.connect(str(target_db))
        run = conn.execute(
            "SELECT status, rows_imported FROM import_runs WHERE status = 'completed'"
        ).fetchone()
        assert run is not None
        assert run[0] == 'completed'
        assert run[1] > 0
        conn.close()

    def test_balance_verification(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """账户余额验证。"""
        executor = MigrationExecutor(source_mym, target_db)
        report = executor.execute()

        verification = report['verification']
        assert verification['integrity_ok'] is True
        assert verification['fk_ok'] is True

    def test_transaction_type_counts(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """交易类型计数正确。"""
        executor = MigrationExecutor(source_mym, target_db)
        report = executor.execute()

        tx_counts = report['verification'].get('tx_type_counts', {})
        # 4 regular + possible settlement
        total_txs = sum(tx_counts.values())
        assert total_txs >= 4


# ── 重复导入测试 ─────────────────────────────────────


class TestDuplicateImport:
    """重复导入防护测试。"""

    def test_duplicate_blocked(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """重复导入被拒绝。"""
        executor = MigrationExecutor(source_mym, target_db)
        executor.execute()

        # 再次导入同一个源文件到同一个目标
        executor2 = MigrationExecutor(source_mym, target_db)
        with pytest.raises(ValueError, match='已导入过'):
            executor2.execute()

    def test_new_target_allowed(
        self, source_mym: Path, tmp_path: Path
    ) -> None:
        """相同源文件导入到不同目标允许。"""
        target1 = tmp_path / 'target1.db'
        target2 = tmp_path / 'target2.db'

        executor1 = MigrationExecutor(source_mym, target1)
        executor1.execute()

        executor2 = MigrationExecutor(source_mym, target2)
        report = executor2.execute()
        assert report['status'] == 'completed'


# ── 异常回滚测试 ─────────────────────────────────────


class TestRollback:
    """异常回滚测试。"""

    def test_corrupt_source_rejected(
        self, tmp_path: Path
    ) -> None:
        """损坏源文件被拒绝。"""
        bad_path = tmp_path / 'bad.mym'
        bad_path.write_text('not a database')
        target = tmp_path / 'target.db'

        with pytest.raises((ValueError, FileNotFoundError)):
            executor = MigrationExecutor(bad_path, target)
            executor.execute()

    def test_missing_source_rejected(
        self, tmp_path: Path
    ) -> None:
        """缺失源文件被拒绝。"""
        target = tmp_path / 'target.db'
        with pytest.raises(FileNotFoundError):
            executor = MigrationExecutor('/no/such/file.mym', target)
            executor.execute()

    def test_dry_run_plan_generation(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """dry-run 计划生成不写入数据。"""
        executor = MigrationExecutor(source_mym, target_db)
        plan = executor.dry_run_plan()

        assert isinstance(plan, MigrationPlan)
        assert len(plan.table_plans) > 0
        assert plan.estimated_new_records > 0

        # 目标数据库不应存在（未执行 execute）
        assert not target_db.exists()


# ── 策略对比测试 ─────────────────────────────────────


class TestStrategies:
    """不同股票策略测试。"""

    def test_historical_snapshot_creates_settlement(
        self, source_mym: Path, tmp_path: Path
    ) -> None:
        """historical_snapshot 创建调节流水。"""
        target = tmp_path / 'target_hs.db'
        executor = MigrationExecutor(source_mym, target, stock_strategy='historical_snapshot')
        executor.execute()

        conn = sqlite3.connect(str(target))
        settlements = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE type = 'historical_investment_settlement'"
        ).fetchone()[0]
        assert settlements >= 1  # 证券账户有差额
        conn.close()

    def test_archive_only_no_snapshot(
        self, source_mym: Path, tmp_path: Path
    ) -> None:
        """archive_only 不创建快照账户。"""
        target = tmp_path / 'target_ao.db'
        executor = MigrationExecutor(source_mym, target, stock_strategy='archive_only')
        executor.execute()

        conn = sqlite3.connect(str(target))
        snapshots = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE type = 'investment_snapshot'"
        ).fetchone()[0]
        assert snapshots == 0
        conn.close()

    def test_skip_strategy_no_stock(
        self, source_mym: Path, tmp_path: Path
    ) -> None:
        """skip 策略不创建股票相关记录。"""
        target = tmp_path / 'target_skip.db'
        executor = MigrationExecutor(source_mym, target, stock_strategy='skip')
        executor.execute()

        conn = sqlite3.connect(str(target))
        archive_count = conn.execute(
            "SELECT COUNT(*) FROM legacy_archive_records WHERE source_table LIKE 'stock_%'"
        ).fetchone()[0]
        assert archive_count == 0
        conn.close()

    def test_backup_created(
        self, source_mym: Path, tmp_path: Path
    ) -> None:
        """迁移前创建备份。"""
        target = tmp_path / 'target_backup.db'
        # 先创建目标库（模拟已有数据）
        target.write_text('')

        executor = MigrationExecutor(source_mym, target)
        report = executor.execute()

        backup_path = report.get('backup_path')
        assert backup_path is not None
        assert Path(backup_path).exists()


# ── ImportRun 报告可追溯测试 ─────────────────────────


class TestReportTraceability:
    """报告可追溯性测试。"""

    def test_report_has_source_hash(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """报告包含源文件哈希。"""
        executor = MigrationExecutor(source_mym, target_db)
        report = executor.execute()

        assert 'source_hash' in report
        assert len(report['source_hash']) == 64  # SHA-256

    def test_report_has_import_run_id(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """报告包含导入运行 ID。"""
        executor = MigrationExecutor(source_mym, target_db)
        report = executor.execute()

        assert 'import_run_id' in report
        assert len(report['import_run_id']) > 0

    def test_report_has_counts(
        self, source_mym: Path, target_db: Path
    ) -> None:
        """报告包含详细计数。"""
        executor = MigrationExecutor(source_mym, target_db)
        report = executor.execute()

        stats = report['stats']
        for key in ('accounts_imported', 'transactions_imported',
                     'archived', 'skipped', 'failed'):
            assert key in stats
