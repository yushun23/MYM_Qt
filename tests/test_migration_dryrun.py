"""旧 .mym 迁移 dry-run 测试。

覆盖：MigrationPlan 数据结构、金额转换验证器、
交易/账户类型映射、Settings 白名单、LegacyMapper 映射计划、
MigrationService dry-run、幂等性验证、股票策略。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mym2.importers.legacy_mym.mapper import LegacyMapper
from mym2.importers.legacy_mym.migration_plan import (
    AccountBalancePlan,
    MigrationPlan,
    MigrationRisk,
    PendingConfirmation,
    TablePlan,
)
from mym2.importers.legacy_mym.migration_service import (
    DryRunResult,
    MigrationService,
    dry_run_migration,
)
from mym2.importers.legacy_mym.source_reader import SourceReader
from mym2.importers.legacy_mym.validators import (
    ValidationReport,
    build_balance_confirmation,
    convert_amount_to_minor,
    is_settings_allowed,
    is_settings_blocked,
    map_account_type,
    map_transaction_type,
    validate_stock_strategy,
)

# ── 构建测试用脱敏 legacy .mym fixture ────────────────


def _build_migration_test_mym(db_path: Path) -> None:
    """创建一个完整的脱敏旧 .mym 用于迁移测试。

    包含：accounts、categories、transactions、budget_months、
    budget_items、budget_lines、settings、stock_accounts、stock_trades、
    stock_cash_flows、ai_chat_messages。
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode=WAL')

    # accounts（包含链接证券账户和多种类型）
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
            (5, '投资理财', 'System', 1, '系统'),
        ],
    )

    # transactions（包含多种类型）
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
            (10, '2026-06-10', '未知交易类型X', 1, 2, None, 30.00, '测试未知', 0),
        ],
    )

    # budget_months
    conn.execute('''
        CREATE TABLE budget_months (
            id INTEGER PRIMARY KEY,
            year INTEGER,
            month INTEGER
        )
    ''')
    conn.executemany(
        'INSERT INTO budget_months VALUES (?,?,?)',
        [(1, 2026, 6), (2, 2026, 7)],
    )

    # budget_items
    conn.execute('''
        CREATE TABLE budget_items (
            id INTEGER PRIMARY KEY,
            name TEXT,
            amount REAL,
            category_id INTEGER,
            budget_month_id INTEGER
        )
    ''')
    conn.executemany(
        'INSERT INTO budget_items VALUES (?,?,?,?,?)',
        [
            (1, '餐饮预算', 2000.00, 1, 1),
            (2, '交通预算', 500.00, 2, 1),
        ],
    )

    # budget_lines
    conn.execute('''
        CREATE TABLE budget_lines (
            id INTEGER PRIMARY KEY,
            budget_month_id INTEGER,
            category_id INTEGER,
            amount REAL,
            note TEXT
        )
    ''')
    conn.executemany(
        'INSERT INTO budget_lines VALUES (?,?,?,?,?)',
        [
            (1, 1, 1, 2000.00, '6月餐饮'),
            (2, 1, 2, 500.00, '6月交通'),
        ],
    )

    # settings（含白名单和敏感键）
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
            ('font_size', '14'),
            ('api_key', 'blocked-value'),
            ('proxy_password', 'placeholder'),
            ('password_hash', 'blocked-value'),
            ('openai_api_key', 'blocked-value'),
            ('unknown_pref', 'some_value'),
            ('currency_display', 'CNY'),
        ],
    )

    # stock_accounts
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

    # stock_trades
    conn.execute('''
        CREATE TABLE stock_trades (
            id INTEGER PRIMARY KEY,
            stock_account_id INTEGER,
            trade_date TEXT,
            symbol TEXT,
            quantity REAL,
            price REAL,
            amount REAL,
            trade_type TEXT
        )
    ''')
    conn.execute(
        'INSERT INTO stock_trades VALUES (?,?,?,?,?,?,?,?)',
        (1, 1, '2026-06-15', '000001', 100, 12.50, 1250.00, '买入'),
    )

    # stock_cash_flows
    conn.execute('''
        CREATE TABLE stock_cash_flows (
            id INTEGER PRIMARY KEY,
            stock_account_id INTEGER,
            date TEXT,
            amount REAL,
            flow_type TEXT
        )
    ''')
    conn.execute(
        'INSERT INTO stock_cash_flows VALUES (?,?,?,?,?)',
        (1, 1, '2026-06-01', 50000.00, 'deposit'),
    )

    # stock_quotes
    conn.execute('''
        CREATE TABLE stock_quotes (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            price REAL,
            date TEXT
        )
    ''')
    conn.execute(
        'INSERT INTO stock_quotes VALUES (?,?,?,?)',
        (1, '000001', 13.00, '2026-06-30'),
    )

    # ai_chat_messages
    conn.execute('''
        CREATE TABLE ai_chat_messages (
            id INTEGER PRIMARY KEY,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    ''')
    conn.execute(
        'INSERT INTO ai_chat_messages VALUES (?,?,?,?)',
        (1, 'user', '帮我记账', '2026-06-01'),
    )

    # schema_migrations（应跳过）
    conn.execute('''
        CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY
        )
    ''')
    conn.execute(
        'INSERT INTO schema_migrations VALUES (?)',
        ('001_initial',),
    )

    conn.commit()
    conn.close()


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def migration_test_mym(tmp_path: Path) -> Path:
    """创建脱敏测试用 .mym 文件。"""
    db_path = tmp_path / 'test_migration.mym'
    _build_migration_test_mym(db_path)
    return db_path


@pytest.fixture
def source_reader(migration_test_mym: Path) -> SourceReader:
    """返回已打开的 SourceReader。"""
    with SourceReader(migration_test_mym) as reader:
        yield reader


@pytest.fixture
def legacy_mapper(source_reader: SourceReader) -> LegacyMapper:
    """返回 LegacyMapper 实例。"""
    return LegacyMapper(source_reader, stock_strategy='historical_snapshot')


@pytest.fixture
def migration_service(migration_test_mym: Path) -> MigrationService:
    """返回 MigrationService 实例。"""
    return MigrationService(migration_test_mym, stock_strategy='historical_snapshot')


# ── MigrationPlan 数据结构测试 ──────────────────────


class TestMigrationPlan:
    """MigrationPlan 数据结构测试。"""

    def test_empty_plan_serializes(self) -> None:
        """空计划可序列化。"""
        plan = MigrationPlan()
        plan.generated_at = MigrationPlan.utc_now_iso()
        json_str = plan.to_json()
        data = json.loads(json_str)
        assert data['plan_version'] == '1.0.0'
        assert data['table_plans'] == []
        assert data['estimated_new_records'] == 0

    def test_roundtrip(self) -> None:
        """JSON 序列化/反序列化一致性。"""
        plan = MigrationPlan()
        plan.generated_at = MigrationPlan.utc_now_iso()
        plan.source_path = '/test/path.mym'
        plan.source_hash = 'abc123'
        plan.stock_strategy = 'historical_snapshot'
        plan.estimated_new_records = 42

        plan.table_plans.append(
            TablePlan('accounts', 5, rows_to_migrate=4, rows_failed=1, note='test')
        )
        plan.table_plans.append(
            TablePlan('transactions', 10, rows_to_migrate=9, note='')
        )
        plan.account_balance_plans.append(
            AccountBalancePlan(1, '现金', 'Asset', 100.0, 10000, 9999, 1)
        )
        plan.pending_confirmations.append(
            PendingConfirmation('未知', 'item1', 'reason1', 'suggest1')
        )
        plan.risks.append(
            MigrationRisk('high', 'test risk', 'accounts', 'mitigation')
        )
        plan.warnings.append('warning 1')

        json_str = plan.to_json()
        plan2 = MigrationPlan.from_json(json_str)

        assert plan2.source_hash == 'abc123'
        assert plan2.stock_strategy == 'historical_snapshot'
        assert plan2.estimated_new_records == 42
        assert len(plan2.table_plans) == 2
        assert len(plan2.account_balance_plans) == 1
        assert len(plan2.pending_confirmations) == 1
        assert len(plan2.risks) == 1

    def test_stable_sorting(self) -> None:
        """确保序列化输出稳定排序。"""
        plan = MigrationPlan()
        plan.table_plans = [
            TablePlan('z_table', 1),
            TablePlan('a_table', 2),
        ]
        plan.account_balance_plans = [
            AccountBalancePlan(2, 'b', 'Asset', 0, 0, 0, 0),
            AccountBalancePlan(1, 'a', 'Asset', 0, 0, 0, 0),
        ]

        json1 = plan.to_json()
        json2 = plan.to_json()
        assert json1 == json2

        data = json.loads(json1)
        assert data['table_plans'][0]['table_name'] == 'a_table'
        assert data['table_plans'][1]['table_name'] == 'z_table'
        assert data['account_balance_plans'][0]['legacy_id'] == 1
        assert data['account_balance_plans'][1]['legacy_id'] == 2

    def test_utc_now_valid(self) -> None:
        """utc_now_iso 返回合法 ISO 字符串。"""
        ts = MigrationPlan.utc_now_iso()
        assert 'T' in ts
        assert len(ts) >= 19


# ── 金额转换验证器测试 ───────────────────────────────


class TestAmountConversion:
    """金额转换测试。"""

    def test_integer(self) -> None:
        """整数金额转换。"""
        r = convert_amount_to_minor(100)
        assert r.minor == 10000
        assert r.is_acceptable

    def test_two_decimals(self) -> None:
        """两位小数金额转换。"""
        r = convert_amount_to_minor(123.45)
        assert r.minor == 12345
        assert r.is_acceptable

    def test_zero(self) -> None:
        """零金额。"""
        r = convert_amount_to_minor(0.0)
        assert r.minor == 0
        assert r.is_acceptable

    def test_negative(self) -> None:
        """负金额。"""
        r = convert_amount_to_minor(-50.00)
        assert r.minor == -5000
        assert r.is_acceptable

    def test_none(self) -> None:
        """None 金额。"""
        r = convert_amount_to_minor(None)
        assert r.minor == 0
        assert r.is_acceptable

    def test_one_cent(self) -> None:
        """1 分精确转换。"""
        r = convert_amount_to_minor(0.01)
        assert r.minor == 1
        assert r.is_acceptable

    def test_one_yuan(self) -> None:
        """1 元精确转换。"""
        r = convert_amount_to_minor(1.00)
        assert r.minor == 100
        assert r.is_acceptable

    def test_fractional_cent_rounds(self) -> None:
        """小数分四舍五入。"""
        r = convert_amount_to_minor(0.005)
        # 0.005 * 100 = 0.5, quantize('1') = 0 or 1
        assert r.is_acceptable

    def test_string_amount(self) -> None:
        """字符串金额。"""
        r = convert_amount_to_minor('99.99')
        assert r.minor == 9999
        assert r.is_acceptable

    def test_large_amount(self) -> None:
        """大额金额。"""
        r = convert_amount_to_minor(9999999.99)
        assert r.minor == 999999999
        assert r.is_acceptable

    def test_diff_tracking(self) -> None:
        """量化差异跟踪。"""
        r = convert_amount_to_minor(0.333)
        # 0.333 → str → '0.333' → Decimal * 100 → 33.3 → quantize → 33
        # roundtrip = 33/100 = 0.33, diff = 0.333 - 0.33 = 0.003, diff_minor = 0
        assert r.diff_minor == 0
        assert r.is_acceptable


# ── 类型映射测试 ─────────────────────────────────────


class TestTypeMapping:
    """交易类型和账户类型映射测试。"""

    def test_known_expense(self) -> None:
        assert map_transaction_type('Expense') == 'expense'

    def test_known_income(self) -> None:
        assert map_transaction_type('Income') == 'income'

    def test_known_transfer(self) -> None:
        assert map_transaction_type('Transfer') == 'transfer'

    def test_known_receivable_advance(self) -> None:
        assert map_transaction_type('垫付/借出') == 'receivable_advance'

    def test_known_receivable_repayment(self) -> None:
        assert map_transaction_type('收回欠款') == 'receivable_repayment'

    def test_known_balance_adjustment(self) -> None:
        assert map_transaction_type('Balance Adjustment') == 'balance_adjustment'

    def test_unknown_type_returns_none(self) -> None:
        assert map_transaction_type('未知交易类型X') is None

    def test_empty_type_returns_none(self) -> None:
        assert map_transaction_type('') is None

    def test_whitespace_type(self) -> None:
        assert map_transaction_type('  ') is None

    def test_known_asset_account(self) -> None:
        assert map_account_type('Asset') == 'cash'

    def test_known_liability_account(self) -> None:
        assert map_account_type('Liability') == 'credit_card'

    def test_known_credit_account(self) -> None:
        assert map_account_type('Credit') == 'credit_card'

    def test_known_receivable_account(self) -> None:
        assert map_account_type('Receivable') == 'receivable'

    def test_unknown_account_type(self) -> None:
        assert map_account_type('UnknownType') is None


# ── Settings 白名单测试 ──────────────────────────────


class TestSettingsFiltering:
    """Settings 过滤测试。"""

    def test_theme_allowed(self) -> None:
        assert is_settings_allowed('theme') is True

    def test_language_allowed(self) -> None:
        assert is_settings_allowed('language') is True

    def test_font_size_allowed(self) -> None:
        assert is_settings_allowed('font_size') is True

    def test_currency_display_allowed(self) -> None:
        assert is_settings_allowed('currency_display') is True

    def test_api_key_blocked(self) -> None:
        assert is_settings_allowed('api_key') is False

    def test_password_blocked(self) -> None:
        assert is_settings_allowed('password_hash') is False

    def test_token_blocked(self) -> None:
        assert is_settings_allowed('session_token') is False

    def test_proxy_password_blocked(self) -> None:
        assert is_settings_allowed('proxy_password') is False

    def test_is_blocked_api_key(self) -> None:
        assert is_settings_blocked('api_key') is True

    def test_is_blocked_password(self) -> None:
        assert is_settings_blocked('password_hash') is True

    def test_not_blocked_theme(self) -> None:
        assert is_settings_blocked('theme') is False

    def test_pending_action_blocked(self) -> None:
        assert is_settings_blocked('ai_pending_action') is True

    def test_unknown_pref_not_allowed(self) -> None:
        """不在白名单且不敏感的键拒迁。"""
        assert is_settings_allowed('unknown_pref') is False
        assert is_settings_blocked('unknown_pref') is False


# ── 股票策略验证测试 ─────────────────────────────────


class TestStockStrategy:
    """股票策略验证测试。"""

    def test_valid_historical_snapshot(self) -> None:
        assert validate_stock_strategy('historical_snapshot') is True

    def test_valid_archive_only(self) -> None:
        assert validate_stock_strategy('archive_only') is True

    def test_valid_skip(self) -> None:
        assert validate_stock_strategy('skip') is True

    def test_invalid_strategy(self) -> None:
        assert validate_stock_strategy('invalid') is False

    def test_service_rejects_invalid(self, migration_test_mym: Path) -> None:
        """MigrationService 拒绝无效策略。"""
        with pytest.raises(ValueError):
            MigrationService(migration_test_mym, stock_strategy='bad_strategy')


# ── LegacyMapper 映射计划测试 ────────────────────────


class TestLegacyMapper:
    """LegacyMapper 测试。"""

    def test_builds_plan(self, legacy_mapper: LegacyMapper) -> None:
        """构建完整计划成功。"""
        plan = legacy_mapper.build_plan()
        assert isinstance(plan, MigrationPlan)
        assert len(plan.table_plans) > 0

    def test_accounts_in_plan(self, legacy_mapper: LegacyMapper) -> None:
        """accounts 表有迁移计划。"""
        plan = legacy_mapper.build_plan()
        acct_plan = next(
            (tp for tp in plan.table_plans if tp.table_name == 'accounts'), None
        )
        assert acct_plan is not None
        assert acct_plan.total_rows == 5
        assert acct_plan.rows_to_migrate >= 4  # 非链接账户

    def test_categories_in_plan(self, legacy_mapper: LegacyMapper) -> None:
        """categories 表有迁移计划。"""
        plan = legacy_mapper.build_plan()
        cat_plan = next(
            (tp for tp in plan.table_plans if tp.table_name == 'categories'), None
        )
        assert cat_plan is not None
        assert cat_plan.total_rows == 5
        assert cat_plan.rows_to_migrate == 5

    def test_transactions_in_plan(self, legacy_mapper: LegacyMapper) -> None:
        """transactions 表有迁移计划。"""
        plan = legacy_mapper.build_plan()
        txn_plan = next(
            (tp for tp in plan.table_plans if tp.table_name == 'transactions'), None
        )
        assert txn_plan is not None
        assert txn_plan.total_rows == 10
        assert txn_plan.rows_to_migrate == 10

    def test_budget_months_in_plan(self, legacy_mapper: LegacyMapper) -> None:
        """budget_months 映射到 budget_periods。"""
        plan = legacy_mapper.build_plan()
        bm_plan = next(
            (tp for tp in plan.table_plans if tp.table_name == 'budget_months'), None
        )
        assert bm_plan is not None
        assert bm_plan.total_rows == 2
        assert bm_plan.rows_to_migrate == 2

    def test_budget_items_in_plan(self, legacy_mapper: LegacyMapper) -> None:
        """budget_items 有迁移计划。"""
        plan = legacy_mapper.build_plan()
        bi_plan = next(
            (tp for tp in plan.table_plans if tp.table_name == 'budget_items'), None
        )
        assert bi_plan is not None
        assert bi_plan.total_rows == 2

    def test_budget_lines_in_plan(self, legacy_mapper: LegacyMapper) -> None:
        """budget_lines 有迁移计划。"""
        plan = legacy_mapper.build_plan()
        bl_plan = next(
            (tp for tp in plan.table_plans if tp.table_name == 'budget_lines'), None
        )
        assert bl_plan is not None
        assert bl_plan.total_rows == 2
        assert bl_plan.rows_to_migrate == 2

    def test_stock_tables_archived(self, legacy_mapper: LegacyMapper) -> None:
        """股票表标记为归档。"""
        plan = legacy_mapper.build_plan()
        for tbl in ('stock_accounts', 'stock_trades', 'stock_cash_flows', 'stock_quotes'):
            tp = next(
                (t for t in plan.table_plans if t.table_name == tbl), None
            )
            assert tp is not None, f'{tbl} should be in plan'
            assert tp.rows_to_archive > 0, f'{tbl} should be archived'

    def test_schema_migrations_skipped(self, legacy_mapper: LegacyMapper) -> None:
        """schema_migrations 标记跳过。"""
        plan = legacy_mapper.build_plan()
        sm = next(
            (tp for tp in plan.table_plans if tp.table_name == 'schema_migrations'),
            None,
        )
        assert sm is not None
        assert sm.rows_to_skip > 0

    def test_ai_chat_archived(self, legacy_mapper: LegacyMapper) -> None:
        """AI 聊天归档到通用归档。"""
        plan = legacy_mapper.build_plan()
        ai = next(
            (tp for tp in plan.table_plans if tp.table_name == 'ai_chat_messages'),
            None,
        )
        assert ai is not None
        assert ai.rows_to_archive > 0
        assert '归档' in ai.note

    def test_settings_whitelisted(self, legacy_mapper: LegacyMapper) -> None:
        """settings 仅迁移白名单项。"""
        plan = legacy_mapper.build_plan()
        st = next(
            (tp for tp in plan.table_plans if tp.table_name == 'settings'), None
        )
        assert st is not None
        # theme, language, font_size, currency_display = 4 条白名单
        assert st.rows_to_migrate >= 4
        # api_key, proxy_password, password_hash, openai_api_key, unknown_pref = 5 跳过
        assert st.rows_to_skip >= 5

    def test_unknown_transaction_type_recorded(self, legacy_mapper: LegacyMapper) -> None:
        """未知交易类型记录为需确认。"""
        plan = legacy_mapper.build_plan()
        unknown_confs = [
            c for c in plan.pending_confirmations
            if c.category == '未知交易类型'
        ]
        assert len(unknown_confs) >= 1

    def test_linked_stock_detected(self, legacy_mapper: LegacyMapper) -> None:
        """链接证券账户被识别。"""
        plan = legacy_mapper.build_plan()
        stock_balances = [
            a for a in plan.account_balance_plans if a.is_linked_stock
        ]
        assert len(stock_balances) >= 1
        for sb in stock_balances:
            assert sb.strategy == 'historical_snapshot'

    def test_balance_plans_populated(self, legacy_mapper: LegacyMapper) -> None:
        """账户余额计划全部填充。"""
        plan = legacy_mapper.build_plan()
        assert len(plan.account_balance_plans) == 5

    def test_risks_populated(self, legacy_mapper: LegacyMapper) -> None:
        """风险列表生成。"""
        plan = legacy_mapper.build_plan()
        assert len(plan.risks) > 0

    def test_estimated_records(self, legacy_mapper: LegacyMapper) -> None:
        """预估记录数 > 0。"""
        plan = legacy_mapper.build_plan()
        assert plan.estimated_new_records > 0

    def test_archive_only_strategy(self, migration_test_mym: Path) -> None:
        """archive_only 策略：股票不创建快照。"""
        with SourceReader(migration_test_mym) as reader:
            mapper = LegacyMapper(reader, stock_strategy='archive_only')
            plan = mapper.build_plan()

        stock_balances = [
            a for a in plan.account_balance_plans if a.is_linked_stock
        ]
        for sb in stock_balances:
            assert sb.strategy == 'archive_only'
            assert '仅归档' in sb.note

    def test_skip_strategy(self, migration_test_mym: Path) -> None:
        """skip 策略：股票表跳过。"""
        with SourceReader(migration_test_mym) as reader:
            mapper = LegacyMapper(reader, stock_strategy='skip')
            plan = mapper.build_plan()

        for tbl in ('stock_accounts', 'stock_trades'):
            tp = next(
                (t for t in plan.table_plans if t.table_name == tbl), None
            )
            assert tp is not None
            assert tp.rows_to_skip > 0
            assert '跳过' in tp.note

    def test_plan_idempotent_across_two_runs(
        self, migration_test_mym: Path
    ) -> None:
        """两次映射计划 JSON 一致（幂等性）。"""
        def _build_json() -> str:
            with SourceReader(migration_test_mym) as reader:
                mapper = LegacyMapper(reader, stock_strategy='historical_snapshot')
                plan = mapper.build_plan()
                plan.generated_at = MigrationPlan.utc_now_iso()
                plan.source_path = str(migration_test_mym)
                return plan.to_json()

        json1 = _build_json()
        json2 = _build_json()

        # 比较前移除 generated_at
        d1 = json.loads(json1)
        d2 = json.loads(json2)
        d1.pop('generated_at', None)
        d2.pop('generated_at', None)

        assert d1 == d2, '两次 dry-run 计划不一致'


# ── MigrationService dry-run 测试 ────────────────────


class TestMigrationService:
    """MigrationService dry-run 测试。"""

    def test_dry_run_succeeds(self, migration_service: MigrationService) -> None:
        """dry-run 不抛异常。"""
        result = migration_service.dry_run()
        assert isinstance(result, DryRunResult)
        assert result.plan is not None
        assert len(result.plan_json) > 0

    def test_dry_run_json_valid(self, migration_service: MigrationService) -> None:
        """dry-run JSON 输出可解析。"""
        result = migration_service.dry_run()
        data = json.loads(result.plan_json)
        assert 'plan_version' in data
        assert 'table_plans' in data
        assert 'account_balance_plans' in data

    def test_dry_run_no_business_data_created(
        self, migration_service: MigrationService, tmp_path: Path
    ) -> None:
        """dry-run 不创建目标业务数据文件。"""
        before = set(tmp_path.iterdir())
        migration_service.dry_run()
        after = set(tmp_path.iterdir())
        new_files = after - before
        assert not any(f.suffix == '.db' for f in new_files)

    def test_dry_run_to_file(
        self, migration_service: MigrationService, tmp_path: Path
    ) -> None:
        """dry_run_to_file 写入 JSON 文件。"""
        out = tmp_path / 'plan.json'
        migration_service.dry_run_to_file(out)
        assert out.exists()
        content = out.read_text(encoding='utf-8')
        assert 'table_plans' in content

    def test_dry_run_idempotent(self, migration_service: MigrationService) -> None:
        """两次 dry-run 的 JSON 计划一致。"""
        result1 = migration_service.dry_run()
        result2 = migration_service.dry_run()

        is_same = MigrationService.verify_idempotent(
            result1.plan_json, result2.plan_json
        )
        assert is_same, '两次 dry-run JSON 计划不一致'

    def test_convenience_function(self, migration_test_mym: Path, tmp_path: Path) -> None:
        """便捷函数 dry_run_migration 可正常执行。"""
        out = tmp_path / 'conv_plan.json'
        result = dry_run_migration(
            migration_test_mym,
            stock_strategy='historical_snapshot',
            output_json=out,
        )
        assert isinstance(result, DryRunResult)
        assert out.exists()

    def test_no_settings_values_in_plan(
        self, migration_service: MigrationService
    ) -> None:
        """计划不泄露 settings 敏感值。"""
        result = migration_service.dry_run()
        assert 'sk-test' not in result.plan_json
        assert '$2b$12$' not in result.plan_json
        assert 'placeholder' not in result.plan_json

    def test_stock_strategy_in_metadata(
        self, migration_service: MigrationService
    ) -> None:
        """计划元数据包含股票策略。"""
        result = migration_service.dry_run()
        data = json.loads(result.plan_json)
        assert data['stock_strategy'] == 'historical_snapshot'


# ── 余额确认构建测试 ─────────────────────────────────


class TestBalanceConfirmation:
    """余额差异确认构建测试。"""

    def test_builds_confirmation(self) -> None:
        """构建余额差异确认。"""
        conf = build_balance_confirmation(
            account_id=4,
            account_name='证券账户',
            account_type='Asset',
            legacy_balance_real=80000.00,
            recomputed_minor=5000000,  # 50000.00 元
        )
        assert conf.category == '余额差异'
        assert '证券账户' in conf.item
        assert '链接证券' in conf.suggestion


# ── 验证报告数据结构测试 ────────────────────────────


class TestValidationReport:
    """ValidationReport 数据结构测试。"""

    def test_empty_report(self) -> None:
        report = ValidationReport()
        assert report.amount_conversions == []
        assert report.errors == []

    def test_report_with_conversions(self) -> None:
        report = ValidationReport()
        report.amount_conversions.append(
            convert_amount_to_minor(123.45)
        )
        assert len(report.amount_conversions) == 1
        assert report.amount_conversions[0].minor == 12345
