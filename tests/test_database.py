"""MYM2 数据库基座测试。

验证：引擎创建、会话、模型导入、迁移、完整性、无 REAL 列。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from mym2.db.base import Base
from mym2.db.engine import create_mym2_engine
from mym2.db.migrate import set_alembic_ini_path, upgrade_to_head
from mym2.db.models import (
    Account,
    AppSetting,
    AuditEvent,
    BudgetLine,
    BudgetPeriod,
    Category,
    ImportRun,
    LegacyArchiveRecord,
    LegacyIdMap,
    Transaction,
)
from mym2.db.session import (
    get_session,
    init_session_factory,
    remove_session,
    reset_session_factory,
)

ALEMBIC_INI = Path(__file__).resolve().parent.parent / 'alembic.ini'


@pytest.fixture(autouse=True)
def _clean_session() -> None:
    """每个测试后清理 session。"""
    yield
    remove_session()


@pytest.fixture
def temp_db() -> Path:
    """创建临时数据库文件路径。"""
    fd, path = tempfile.mkstemp(suffix='.db', prefix='mym2_test_')
    import os
    os.close(fd)
    yield Path(path)
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def migrated_db(temp_db: Path) -> Path:
    """创建并迁移临时数据库。"""
    set_alembic_ini_path(str(ALEMBIC_INI))
    upgrade_to_head(temp_db)
    reset_session_factory()
    engine = create_mym2_engine(temp_db)
    init_session_factory(engine)
    yield temp_db
    remove_session()
    reset_session_factory()
    engine.dispose()


# ── 引擎测试 ──────────────────────────────────────────

def test_engine_creatable(temp_db: Path) -> None:
    """能创建 SQLite 引擎。"""
    engine = create_mym2_engine(temp_db)
    assert engine is not None
    engine.dispose()


def test_pragma_foreign_keys_on(temp_db: Path) -> None:
    """PRAGMA foreign_keys 为 ON。"""
    engine = create_mym2_engine(temp_db)
    with engine.connect() as conn:
        result = conn.execute(text('PRAGMA foreign_keys'))
        row = result.fetchone()
        assert row is not None and row[0] == 1
    engine.dispose()


def test_pragma_wal_enabled(temp_db: Path) -> None:
    """journal_mode 为 WAL。"""
    engine = create_mym2_engine(temp_db)
    with engine.connect() as conn:
        result = conn.execute(text('PRAGMA journal_mode'))
        row = result.fetchone()
        assert row is not None and row[0].lower() == 'wal'
    engine.dispose()


# ── 模型导入测试 ──────────────────────────────────────

def test_all_models_importable() -> None:
    """所有 10 个模型可导入。"""
    models = [
        Account, AppSetting, AuditEvent, BudgetLine, BudgetPeriod,
        Category, ImportRun, LegacyArchiveRecord, LegacyIdMap, Transaction,
    ]
    for m in models:
        assert m is not None
        assert hasattr(m, '__tablename__')


def test_models_have_tables() -> None:
    """所有模型都注册到 Base.metadata。"""
    expected = {
        'accounts', 'app_settings', 'audit_events', 'budget_periods',
        'budget_lines', 'categories', 'import_runs',
        'legacy_archive_records', 'legacy_id_map', 'transactions',
    }
    actual = set(Base.metadata.tables.keys())
    assert expected == actual, f'表名不匹配: {expected - actual} / {actual - expected}'


# ── 迁移测试 ──────────────────────────────────────────

def test_migration_creates_all_tables(migrated_db: Path) -> None:
    """迁移后所有表都存在。"""
    engine = create_mym2_engine(migrated_db)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        'alembic_version',
        'accounts', 'app_settings', 'audit_events', 'budget_periods',
        'budget_lines', 'categories', 'import_runs',
        'legacy_archive_records', 'legacy_id_map', 'transactions',
    }
    assert tables == expected, f'缺失表: {expected - tables}, 多余表: {tables - expected}'
    engine.dispose()


def test_integrity_check_ok(migrated_db: Path) -> None:
    """PRAGMA integrity_check 返回 ok。"""
    engine = create_mym2_engine(migrated_db)
    with engine.connect() as conn:
        result = conn.execute(text('PRAGMA integrity_check'))
        row = result.fetchone()
        assert row is not None and row[0] == 'ok', f'integrity_check: {row}'
    engine.dispose()


def test_foreign_key_check_no_rows(migrated_db: Path) -> None:
    """PRAGMA foreign_key_check 返回零行。"""
    engine = create_mym2_engine(migrated_db)
    with engine.connect() as conn:
        result = conn.execute(text('PRAGMA foreign_key_check'))
        rows = result.fetchall()
        assert len(rows) == 0, f'foreign_key_check 有 {len(rows)} 行违规: {rows}'
    engine.dispose()


def test_no_real_columns(migrated_db: Path) -> None:
    """schema 中没有任何 REAL 类型的金额列。"""
    engine = create_mym2_engine(migrated_db)
    inspector = inspect(engine)
    real_cols: list[str] = []
    for table_name in inspector.get_table_names():
        for col in inspector.get_columns(table_name):
            col_type = str(col['type']).upper()
            if 'REAL' in col_type:
                real_cols.append(f'{table_name}.{col["name"]} ({col_type})')
    assert len(real_cols) == 0, f'发现 REAL 类型列: {real_cols}'
    engine.dispose()


def test_amount_columns_are_integer(migrated_db: Path) -> None:
    """所有 *_minor 金额列为 INTEGER。"""
    engine = create_mym2_engine(migrated_db)
    inspector = inspect(engine)
    minor_cols: list[tuple[str, str, str]] = []
    for table_name in inspector.get_table_names():
        for col in inspector.get_columns(table_name):
            if col['name'].endswith('_minor'):
                col_type = str(col['type']).upper()
                minor_cols.append((table_name, col['name'], col_type))
                assert 'INTEGER' in col_type, f'{table_name}.{col["name"]} 不是 INTEGER: {col_type}'
    assert len(minor_cols) > 0, '没有发现 *_minor 金额列'
    engine.dispose()


def test_transaction_indexes_exist(migrated_db: Path) -> None:
    """transactions 表有 4 个指定索引。"""
    engine = create_mym2_engine(migrated_db)
    inspector = inspect(engine)
    indexes = inspector.get_indexes('transactions')
    index_names = {idx['name'] for idx in indexes}
    expected = {
        'ix_trans_date_id', 'ix_trans_out_date',
        'ix_trans_in_date', 'ix_trans_cat_date',
    }
    assert expected.issubset(index_names), f'缺失索引: {expected - index_names}'
    engine.dispose()


def test_legacy_id_map_index_exists(migrated_db: Path) -> None:
    """legacy_id_map 有指定索引。"""
    engine = create_mym2_engine(migrated_db)
    inspector = inspect(engine)
    indexes = inspector.get_indexes('legacy_id_map')
    index_names = {idx['name'] for idx in indexes}
    assert 'ix_legacy_lookup' in index_names


# ── Session 测试 ──────────────────────────────────────

def test_session_factory_initializable(temp_db: Path) -> None:
    """Session 工厂可初始化。"""
    engine = create_mym2_engine(temp_db)
    factory = init_session_factory(engine)
    assert factory is not None
    engine.dispose()


def test_session_crud(migrated_db: Path) -> None:
    """Session 可执行基本 CRUD。"""
    session = get_session()
    cat = Category(name='测试分类', type='expense')
    session.add(cat)
    session.commit()

    fetched = session.get(Category, cat.id)
    assert fetched is not None
    assert fetched.name == '测试分类'

    session.delete(fetched)
    session.commit()

    assert session.get(Category, cat.id) is None


def test_each_test_database_isolated(migrated_db: Path) -> None:
    """每个测试使用隔离数据库 — 表存在但无数据。"""
    session = get_session()
    count = session.query(Category).count()
    assert count == 0, f'隔离库中不应有数据，但查到 {count} 行'


# ── upgrade_to_head 函数测试 ──────────────────────────
