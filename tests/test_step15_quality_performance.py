"""第 15 步：全量质量、异常恢复与性能整理验收测试。"""

from __future__ import annotations

import importlib.util
import logging
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym2.charts.chart_html import BASE_URL, build_chart_html
from mym2.core.logging import install_excepthook, setup_logging
from mym2.db.engine import create_mym2_engine
from mym2.db.migrate import upgrade_to_head
from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType, CategoryType
from mym2.importers.legacy_mym.executor import MigrationExecutor
from mym2.repositories.transaction_repo import TransactionFilter, TransactionRepository
from mym2.services.backup_service import RESTORE_CONFIRMATION, BackupService
from mym2.services.balance_service import BalanceService
from mym2.services.diagnostics_service import DiagnosticsOptions, DiagnosticsService
from mym2.services.report_service import ReportFilter
from mym2.services.settings_service import SettingsService
from mym2.ui.theme import apply_theme
from mym2.ui.workers import (
    ReportExportRequest,
    ReportExportWorker,
    TransactionExportRequest,
    TransactionExportWorker,
)
from tests.test_migration_executor import _build_executor_test_mym


def _seed_worker_db(path: Path) -> tuple[str, str]:
    upgrade_to_head(path)
    engine = create_mym2_engine(path)
    try:
        with Session(engine) as session:
            account = Account(
                name='现金',
                type=AccountType.CASH.value,
                is_enabled=True,
                is_editable=True,
                opening_balance_minor=0,
                current_balance_minor=0,
            )
            category = Category(
                name='餐饮',
                type=CategoryType.EXPENSE.value,
                is_enabled=True,
            )
            session.add_all([account, category])
            session.flush()
            session.add(
                Transaction(
                    transaction_date=date(2026, 7, 4),
                    type='expense',
                    account_out_id=account.id,
                    category_id=category.id,
                    amount_minor=1234,
                    note='=formula',
                    source='manual',
                )
            )
            session.commit()
            return account.id, category.id
    finally:
        engine.dispose()


def test_diagnostics_default_excludes_database_secrets_and_full_transactions(
    session: Session,
    tmp_path: Path,
) -> None:
    SettingsService().set(session, 'theme', 'dark')
    session.commit()
    logs_dir = tmp_path / 'logs'
    logger = setup_logging(logs_dir, level=logging.INFO)
    logger.info('api_key=secret-token path=/Users/example/private/mym2.db')
    for handler in logger.handlers:
        handler.flush()

    package = tmp_path / 'diagnostics.zip'
    result = DiagnosticsService().export_package(
        session,
        destination=package,
        logs_dir=logs_dir,
        db_path=tmp_path / 'mym2.db',
        options=DiagnosticsOptions(),
    )

    assert package.exists()
    assert 'database/mym2.db' not in result.included
    assert 'transactions.json' not in result.included
    with zipfile.ZipFile(package) as zf:
        names = set(zf.namelist())
        assert 'manifest.json' in names
        assert 'settings.json' in names
        text = ''.join(
            zf.read(name).decode('utf-8', errors='replace')
            for name in names
            if name.endswith(('.json', '.log', '.jsonl'))
        )
    assert 'secret-token' not in text
    assert '/Users/example/private/mym2.db' not in text
    assert '<redacted>' in text


def test_global_exception_hook_logs_and_shows_dialog(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    logger = setup_logging(tmp_path, level=logging.INFO)
    seen: dict[str, str] = {}

    def _critical(parent, title, message):
        seen['title'] = title
        seen['message'] = message

    monkeypatch.setattr('PySide6.QtWidgets.QMessageBox.critical', _critical)
    monkeypatch.setattr('sys.__excepthook__', lambda *args: None)
    install_excepthook(logger)

    import sys

    sys.excepthook(RuntimeError, RuntimeError('api_key=secret'), None)
    assert seen['title'] == 'MYM2 发生异常'
    assert 'secret' not in seen['message']
    assert '<redacted>' in seen['message']


def test_theme_switch_applies_to_qapplication(qapp) -> None:
    assert apply_theme('light', qapp) == 'light'
    assert '#f6f7fb' in qapp.styleSheet()
    assert apply_theme('dark', qapp) == 'dark'
    assert '#1e1f2b' in qapp.styleSheet()


def test_chart_html_uses_local_echarts_only() -> None:
    assert (BASE_URL / 'echarts.min.js').exists()
    html = build_chart_html({'series': []})
    assert 'src="echarts.min.js"' in html
    assert 'http://' not in html
    assert 'https://' not in html
    assert 'cdn' not in html.lower()


def test_account_balance_can_be_rebuilt_from_transactions(session: Session) -> None:
    account = Account(
        name='现金',
        type=AccountType.CASH.value,
        is_enabled=True,
        is_editable=True,
        opening_balance_minor=10_000,
        current_balance_minor=999_999,
    )
    category = Category(name='餐饮', type=CategoryType.EXPENSE.value, is_enabled=True)
    session.add_all([account, category])
    session.flush()
    session.add(
        Transaction(
            transaction_date=date(2026, 7, 4),
            type='expense',
            account_out_id=account.id,
            category_id=category.id,
            amount_minor=1234,
        )
    )
    session.commit()

    rebuilt = BalanceService().recalculate_account(session, account.id)
    session.commit()
    assert rebuilt == 8766
    assert account.current_balance_minor == 8766


def test_backup_restore_roundtrip_uses_synthetic_database(tmp_path: Path) -> None:
    db_path = tmp_path / 'mym2.db'
    backup_dir = tmp_path / 'backups'
    upgrade_to_head(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            'INSERT INTO app_settings (id, key, value) VALUES (?, ?, ?)',
            ('setting-theme', 'theme', 'dark'),
        )
        conn.commit()
    finally:
        conn.close()

    service = BackupService()
    metadata = service.create_backup(db_path, backup_dir, reason='step15')
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE app_settings SET value = 'light' WHERE key = 'theme'")
        conn.commit()
    finally:
        conn.close()

    result = service.restore_backup(
        backup_dir / metadata.filename,
        db_path,
        expected_sha256=metadata.sha256,
        confirmation_text=RESTORE_CONFIRMATION,
    )
    assert result.restart_required is True
    conn = sqlite3.connect(str(db_path))
    try:
        theme = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'theme'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert theme == 'dark'


def test_migration_mid_transaction_failure_rolls_back_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / 'source.mym'
    target = tmp_path / 'target.db'
    _build_executor_test_mym(source)
    executor = MigrationExecutor(source, target)

    def _fail(*args, **kwargs):
        raise RuntimeError('forced rollback')

    monkeypatch.setattr(executor, '_migrate_transactions', _fail)
    with pytest.raises(RuntimeError, match='forced rollback'):
        executor.execute(backup=False)

    conn = sqlite3.connect(str(target))
    try:
        assert conn.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM import_runs').fetchone()[0] == 0
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        conn.close()


def test_desensitized_legacy_migration_never_persists_secret_fixture_value(
    tmp_path: Path,
) -> None:
    source = tmp_path / 'source.mym'
    target = tmp_path / 'target.db'
    _build_executor_test_mym(source)

    MigrationExecutor(source, target).execute(backup=False)
    raw_target = target.read_bytes()
    assert b'blocked-value' not in raw_target

    conn = sqlite3.connect(str(target))
    try:
        rows = conn.execute('SELECT key, value FROM app_settings').fetchall()
        assert ('theme', 'dark') in rows
        assert all(key not in {'api_key', 'password_hash'} for key, _ in rows)
    finally:
        conn.close()


def test_duplicate_import_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / 'source.mym'
    target = tmp_path / 'target.db'
    _build_executor_test_mym(source)

    MigrationExecutor(source, target).execute(backup=False)
    with pytest.raises(ValueError, match='已导入过'):
        MigrationExecutor(source, target).execute(backup=False)


def test_worker_exports_use_independent_session_and_plain_dtos(tmp_path: Path) -> None:
    db_path = tmp_path / 'worker.db'
    _seed_worker_db(db_path)
    csv_path = tmp_path / 'transactions.csv'
    worker = TransactionExportWorker(
        TransactionExportRequest(
            db_path=str(db_path),
            output_path=str(csv_path),
            filters=TransactionFilter(types=['expense']),
        )
    )
    result = worker.do_work()

    assert result.row_count == 1
    assert "'=formula" in csv_path.read_text(encoding='utf-8-sig')
    assert not hasattr(worker.request, 'parentWidget')

    report_path = tmp_path / 'report.csv'
    report_worker = ReportExportWorker(
        ReportExportRequest(
            db_path=str(db_path),
            output_path=str(report_path),
            kind='monthly_income_expense',
            filters=ReportFilter(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
            ),
            format='csv',
        )
    )
    report_result = report_worker.do_work()
    assert report_result.row_count == 1
    assert report_path.exists()


def test_transaction_type_date_index_exists(tmp_path: Path) -> None:
    db_path = tmp_path / 'indexed.db'
    upgrade_to_head(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        indexes = {
            row[1]
            for row in conn.execute('PRAGMA index_list(transactions)').fetchall()
        }
    finally:
        conn.close()
    assert 'ix_trans_type_date' in indexes


def test_transaction_list_uses_pagination_and_count(session: Session) -> None:
    account = Account(
        name='现金',
        type=AccountType.CASH.value,
        is_enabled=True,
        is_editable=True,
        opening_balance_minor=0,
        current_balance_minor=0,
    )
    session.add(account)
    session.flush()
    session.add_all([
        Transaction(
            transaction_date=date(2026, 7, 4),
            type='expense',
            account_out_id=account.id,
            amount_minor=100 + i,
            note=f'page-{i}',
        )
        for i in range(105)
    ])
    session.commit()

    repo = TransactionRepository(session)
    filters = TransactionFilter(types=['expense'])
    page = repo.query_filtered(filters, page=2, page_size=50)
    assert repo.count_filtered(filters) == 105
    assert page.total == 105
    assert len(page.items) == 50


def test_10000_synthetic_transactions_benchmark() -> None:
    script = Path(__file__).resolve().parent.parent / 'scripts' / 'perf_10000_transactions.py'
    spec = importlib.util.spec_from_file_location('mym2_perf_10000', script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.run_benchmark(rows=10_000)
    assert result['filter_seconds'] < 2.0
    assert result['monthly_report_seconds'] < 2.0
    assert result['transactions_page_refresh_seconds'] < 3.0
