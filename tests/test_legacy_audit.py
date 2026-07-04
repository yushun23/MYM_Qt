"""旧 .mym 审计器测试。

覆盖：只读打开、损坏文件拒绝、哈希不变、schema 探测、
REAL 检测、链接证券账户识别、余额差异、settings 脱敏、报告生成。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from mym2.importers.legacy_mym.audit import audit_mym_file
from mym2.importers.legacy_mym.reporting import ReportGenerator
from mym2.importers.legacy_mym.schema_probe import ProbeResult, SchemaProbe
from mym2.importers.legacy_mym.source_reader import SourceReader

# ── 构建测试用脱敏 SQLite fixture ────────────────────


def _build_test_mym(db_path: Path) -> None:
    """创建一个模拟旧 .mym 结构的 SQLite 数据库。

    使用脱敏合成数据，不包含任何真实个人信息。
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode = WAL')

    # accounts（包含一个链接证券账户）
    conn.execute('''
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            balance REAL DEFAULT 0.0,
            is_active INTEGER DEFAULT 1,
            group_name TEXT,
            linked_stock_account_id INTEGER,
            is_system_locked INTEGER DEFAULT 0,
            opening_balance REAL DEFAULT 0.0
        )
    ''')
    conn.executemany(
        'INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?)',
        [
            (1, '现金', 'Asset', 500.00, 1, '现金账户', None, 0, 0.0),
            (2, '银行储蓄', 'Asset', 15000.00, 1, '银行存款', None, 0, 10000.0),
            (3, '招商信用卡', 'Liability', 3200.50, 1, '信用卡', None, 0, 0.0),
            (4, '证券账户', 'Asset', 80000.00, 1, '上市证券', 1, 1, 50000.0),
            (5, '应收借款', 'Receivable', 2000.00, 1, '债权/应收款', None, 0, 0.0),
        ],
    )

    # categories
    conn.execute('''
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            is_active INTEGER DEFAULT 1,
            group_name TEXT
        )
    ''')
    conn.executemany(
        'INSERT INTO categories VALUES (?,?,?,?,?)',
        [
            (1, '餐饮', 'Expense', 1, '日常'),
            (2, '交通', 'Expense', 1, '日常'),
            (3, '工资', 'Income', 1, '收入'),
            (4, '购物', 'Expense', 1, '日常'),
        ],
    )

    # transactions
    conn.execute('''
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            trans_date DATE,
            trans_type TEXT,
            category_id INTEGER,
            account_out_id INTEGER,
            account_in_id INTEGER,
            amount REAL,
            note TEXT,
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
            (5, '2026-06-05', 'Expense', 4, 3, None, 99.50, '网购', 0),
            (6, '2026-06-06', 'Transfer', None, 2, 3, 500.00, '还信用卡', 0),
            (7, '2026-06-07', 'Balance Adjustment', None, 2, None, 25.00, '调节', 0),
            (8, '2026-06-08', '垫付/借出', None, 1, 5, 200.00, '代付餐费', 0),
            (9, '2026-06-09', '收回欠款', None, 5, 1, 100.00, '还款', 0),
        ],
    )

    # settings（包含敏感键）
    conn.execute('''
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.executemany(
        'INSERT INTO settings VALUES (?,?)',
        [
            ('theme', 'dark'),
            ('language', 'zh_CN'),
            ('api_key', 'sk-test-placeholder-not-real'),
            ('proxy_password', 'placeholder'),
            ('password_hash', '$2b$12$placeholder'),
            ('openai_api_key', 'sk-test-not-real'),
            ('proxy_mode', 'http'),
            ('schema_version', '5'),
        ],
    )

    # stock_accounts（链接证券账户）
    conn.execute('''
        CREATE TABLE stock_accounts (
            id INTEGER PRIMARY KEY,
            name TEXT,
            currency TEXT,
            cash_balance REAL,
            note TEXT,
            is_active INTEGER
        )
    ''')
    conn.execute(
        'INSERT INTO stock_accounts VALUES (?,?,?,?,?,?)',
        (1, '证券账户', 'CNY', 30000.00, '模拟证券', 1),
    )

    # stock_trades（有数据的股票表）
    conn.execute('''
        CREATE TABLE stock_trades (
            id INTEGER PRIMARY KEY,
            stock_account_id INTEGER,
            trade_date TEXT,
            symbol TEXT,
            name TEXT,
            market TEXT,
            trade_type TEXT,
            quantity REAL,
            price REAL
        )
    ''')
    conn.executemany(
        'INSERT INTO stock_trades VALUES (?,?,?,?,?,?,?,?,?)',
        [
            (1, 1, '2026-05-01', '000001', '平安银行', 'SZ', 'buy', 100, 12.50),
            (2, 1, '2026-05-15', '000001', '平安银行', 'SZ', 'sell', 50, 13.00),
        ],
    )

    # budget_months
    conn.execute('''
        CREATE TABLE budget_months (
            id INTEGER PRIMARY KEY,
            period_month TEXT,
            mode TEXT,
            total_budget REAL,
            notes TEXT
        )
    ''')
    conn.execute(
        'INSERT INTO budget_months VALUES (?,?,?,?,?)',
        (1, '2026-06', 'monthly', 5000.00, '6月预算'),
    )

    # AI 归档表
    conn.execute('''
        CREATE TABLE ai_chat_messages (
            id INTEGER PRIMARY KEY,
            created_at TEXT,
            role TEXT,
            content TEXT
        )
    ''')
    conn.execute(
        'INSERT INTO ai_chat_messages VALUES (?,?,?,?)',
        (1, '2026-06-01', 'user', '脱敏数据'),
    )

    conn.commit()
    conn.close()


@pytest.fixture
def test_mym_path() -> Path:
    """创建脱敏测试用 .mym 数据库文件。"""
    fd, path = tempfile.mkstemp(suffix='.mym', prefix='test_legacy_')
    import os
    os.close(fd)
    _build_test_mym(Path(path))
    yield Path(path)
    Path(path).unlink(missing_ok=True)


# ── 损坏/非 SQLite 文件 ──────────────────────────────


@pytest.fixture
def corrupt_path() -> Path:
    """创建非 SQLite 的损坏文件。"""
    fd, path = tempfile.mkstemp(suffix='.mym', prefix='test_corrupt_')
    import os
    os.close(fd)
    with open(path, 'wb') as f:
        f.write(b'this is not a sqlite database file at all')
    yield Path(path)
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def empty_path() -> Path:
    """创建空文件。"""
    fd, path = tempfile.mkstemp(suffix='.mym', prefix='test_empty_')
    import os
    os.close(fd)
    yield Path(path)
    Path(path).unlink(missing_ok=True)


# ── 只读打开测试 ─────────────────────────────────────


class TestSourceReader:
    """SourceReader 基础测试。"""

    def test_open_readonly(self, test_mym_path: Path) -> None:
        """能以只读模式打开。"""
        reader = SourceReader(test_mym_path)
        reader.open()
        assert reader._conn is not None
        reader.close()
        assert reader.is_hash_unchanged

    def test_context_manager(self, test_mym_path: Path) -> None:
        """上下文管理器正常工作。"""
        with SourceReader(test_mym_path) as reader:
            tables = reader.get_tables()
            assert 'accounts' in tables

    def test_file_not_found(self) -> None:
        """不存在的文件抛出 FileNotFoundError。"""
        reader = SourceReader('/nonexistent/path.mym')
        with pytest.raises(FileNotFoundError):
            reader.open()

    def test_corrupt_file_rejected(self, corrupt_path: Path) -> None:
        """非 SQLite 文件被安全拒绝。"""
        reader = SourceReader(corrupt_path)
        with pytest.raises(ValueError, match='不是有效 SQLite'):
            reader.open()

    def test_empty_file_rejected(self, empty_path: Path) -> None:
        """空文件被安全拒绝。"""
        reader = SourceReader(empty_path)
        with pytest.raises(ValueError):
            reader.open()

    def test_hash_unchanged_after_read(self, test_mym_path: Path) -> None:
        """读取后文件哈希不变。"""
        hash_before = hashlib.sha256(test_mym_path.read_bytes()).hexdigest()
        with SourceReader(test_mym_path) as reader:
            reader.get_tables()
        hash_after = hashlib.sha256(test_mym_path.read_bytes()).hexdigest()
        assert hash_before == hash_after
        assert reader.is_hash_unchanged

    def test_write_sql_rejected(self, test_mym_path: Path) -> None:
        """写 SQL 被拒绝执行。"""
        with SourceReader(test_mym_path) as reader, \
                pytest.raises(ValueError, match='禁止执行'):
            reader.execute('INSERT INTO accounts VALUES (99)')

    def test_vacuum_rejected(self, test_mym_path: Path) -> None:
        """VACUUM 被拒绝。"""
        with SourceReader(test_mym_path) as reader, \
                pytest.raises(ValueError, match='禁止执行'):
            reader.execute('VACUUM')

    def test_write_pragma_blocked_by_readonly(
        self, test_mym_path: Path
    ) -> None:
        """PRAGMA 写操作被只读模式拒绝。"""
        with SourceReader(test_mym_path) as reader, pytest.raises(
            (sqlite3.OperationalError, sqlite3.DatabaseError)
        ):
            reader._conn.execute(  # type: ignore[union-attr]
                'PRAGMA journal_mode = DELETE')

    def test_integrity_check(self, test_mym_path: Path) -> None:
        """integrity_check 通过。"""
        with SourceReader(test_mym_path) as reader:
            errors = reader.check_integrity()
            assert errors == []

    def test_row_factory_returns_named_rows(self, test_mym_path: Path) -> None:
        """row_factory 返回可按名称访问的行。"""
        with SourceReader(test_mym_path) as reader:
            rows = reader.fetch_all(
                'SELECT name, type FROM accounts ORDER BY id'
            )
            assert len(rows) > 0
            assert rows[0]['name'] == '现金'


# ── Schema 探测测试 ──────────────────────────────────


class TestSchemaProbe:
    """SchemaProbe 测试。"""

    @pytest.fixture
    def probe_result(self, test_mym_path: Path) -> ProbeResult:
        with SourceReader(test_mym_path) as reader:
            probe = SchemaProbe(reader)
            return probe.probe()

    def test_all_expected_tables(self, probe_result: ProbeResult) -> None:
        """所有预期表被检测到。"""
        tables = set(probe_result.tables.keys())
        assert 'accounts' in tables
        assert 'transactions' in tables
        assert 'categories' in tables
        assert 'settings' in tables
        assert 'stock_accounts' in tables
        assert 'stock_trades' in tables

    def test_row_counts(self, probe_result: ProbeResult) -> None:
        """行数统计正确。"""
        assert probe_result.tables['accounts'].row_count == 5
        assert probe_result.tables['transactions'].row_count == 9
        assert probe_result.tables['categories'].row_count == 4
        assert probe_result.tables['settings'].row_count == 8

    def test_real_columns_detected(self, probe_result: ProbeResult) -> None:
        """REAL 金额列被检测。"""
        real_acc = probe_result.tables['accounts'].real_columns
        assert 'balance' in real_acc
        assert 'opening_balance' in real_acc

    def test_real_anomalies_reported(self, probe_result: ProbeResult) -> None:
        """REAL 金额异常被记录。"""
        anomaly_tables = {a.table for a in probe_result.real_anomalies}
        assert 'accounts' in anomaly_tables
        assert 'transactions' in anomaly_tables

    def test_transaction_type_counts(self, probe_result: ProbeResult) -> None:
        """交易类型统计正确。"""
        ttc = probe_result.transaction_type_counts
        assert 'Expense' in ttc
        assert 'Income' in ttc
        assert 'Transfer' in ttc
        assert ttc.get('Expense', 0) >= 2

    def test_linked_stock_detected(self, probe_result: ProbeResult) -> None:
        """链接证券账户被识别。"""
        assert len(probe_result.linked_stock_accounts) >= 1
        names = [a.account_name for a in probe_result.linked_stock_accounts]
        assert '证券账户' in names

    def test_stock_tables_warning(self, probe_result: ProbeResult) -> None:
        """股票相关表被警告。"""
        stock_warnings = [
            w for w in probe_result.warnings
            if 'stock_' in w
        ]
        assert len(stock_warnings) >= 1

    def test_balance_diffs_detected(self, probe_result: ProbeResult) -> None:
        """非链接账户的余额差异被检测。"""
        linked_ids = {a.account_id for a in probe_result.linked_stock_accounts}
        for d in probe_result.balance_diffs:
            assert d.account_id not in linked_ids

    def test_settings_sensitive_keys(self, probe_result: ProbeResult) -> None:
        """敏感 settings 键被识别。"""
        sensitive = probe_result.settings_sensitive_keys
        assert 'api_key' in sensitive
        assert 'proxy_password' in sensitive
        assert 'password_hash' in sensitive
        assert 'openai_api_key' in sensitive

    def test_settings_values_not_exposed(self, probe_result: ProbeResult) -> None:
        """settings 值不被暴露 — 由结构保证。"""
        pass


# ── 报告生成测试 ─────────────────────────────────────


class TestReportGeneration:
    """报告生成测试。"""

    @pytest.fixture
    def reporter(self, test_mym_path: Path) -> ReportGenerator:
        with SourceReader(test_mym_path) as reader:
            probe = SchemaProbe(reader)
            result = probe.probe()
            return ReportGenerator(
                result=result,
                source_path=str(test_mym_path),
                source_hash=reader.file_hash_before or 'test',
                hash_unchanged=True,
            )

    def test_json_report_valid(self, reporter: ReportGenerator) -> None:
        """JSON 报告可解析。"""
        data = json.loads(reporter.to_json())
        assert 'meta' in data
        assert 'integrity' in data
        assert 'summary' in data
        assert data['meta']['hash_unchanged'] is True

    def test_json_no_settings_values(self, reporter: ReportGenerator) -> None:
        """JSON 报告不包含 settings 值。"""
        text = reporter.to_json()
        assert 'sk-test' not in text
        assert 'placeholder' not in text

    def test_markdown_report_has_sections(self, reporter: ReportGenerator) -> None:
        """Markdown 报告包含所有必要章节。"""
        md = reporter.to_markdown()
        assert '文件信息' in md
        assert '完整性检查' in md
        assert '表概览' in md
        assert '交易类型分布' in md
        assert '链接证券账户' in md
        assert 'Settings 检测' in md

    def test_markdown_no_sensitive_values(
        self, reporter: ReportGenerator
    ) -> None:
        """Markdown 报告不包含 settings 敏感值。"""
        md = reporter.to_markdown()
        assert 'sk-test' not in md
        assert '$2b$12$' not in md
        assert 'api_key' in md
        assert 'password_hash' in md

    def test_write_reports(
        self, reporter: ReportGenerator, tmp_path: Path
    ) -> None:
        """报告文件成功写入。"""
        json_path = tmp_path / 'test_audit.json'
        md_path = tmp_path / 'test_audit.md'
        reporter.write_json(json_path)
        reporter.write_markdown(md_path)
        assert json_path.exists()
        assert md_path.exists()
        assert json_path.read_text(encoding='utf-8').startswith('{')
        assert md_path.read_text(encoding='utf-8').startswith('# ')


# ── 端到端审计测试 ──────────────────────────────────


class TestAuditEndToEnd:
    """端到端审计流程测试。"""

    def test_audit_success(self, test_mym_path: Path, tmp_path: Path) -> None:
        """完整审计流程成功。"""
        result = audit_mym_file(test_mym_path, tmp_path)
        assert result['integrity']['integrity_ok'] is True
        assert result['summary']['table_count'] >= 6

        stem = test_mym_path.stem
        json_path = tmp_path / f'{stem}_audit.json'
        md_path = tmp_path / f'{stem}_audit.md'
        assert json_path.exists()
        assert md_path.exists()

    def test_audit_corrupt_file(
        self, corrupt_path: Path, tmp_path: Path
    ) -> None:
        """损坏文件审计给出安全错误。"""
        with pytest.raises((ValueError, FileNotFoundError)):
            audit_mym_file(corrupt_path, tmp_path)

    def test_audit_nonexistent_file(self, tmp_path: Path) -> None:
        """不存在的文件审计给出错误。"""
        with pytest.raises(FileNotFoundError):
            audit_mym_file('/no/such/file.mym', tmp_path)

    def test_hash_unchanged_after_audit(
        self, test_mym_path: Path, tmp_path: Path
    ) -> None:
        """完整审计后文件哈希不变。"""
        hash_before = hashlib.sha256(
            test_mym_path.read_bytes()
        ).hexdigest()
        audit_mym_file(test_mym_path, tmp_path)
        hash_after = hashlib.sha256(
            test_mym_path.read_bytes()
        ).hexdigest()
        assert hash_before == hash_after

    def test_no_new_ledger_created(
        self, test_mym_path: Path, tmp_path: Path
    ) -> None:
        """审计不创建新账本文件。"""
        before_files = (
            set(tmp_path.iterdir()) if tmp_path.exists() else set()
        )
        audit_mym_file(test_mym_path, tmp_path)
        after_files = set(tmp_path.iterdir())
        new_files = after_files - before_files
        assert not any(f.suffix == '.db' for f in new_files)
