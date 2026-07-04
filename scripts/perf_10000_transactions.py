"""10,000 笔合成流水性能基准。

用法：
    PYTHONPATH=src python scripts/perf_10000_transactions.py
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from sqlalchemy.orm import Session

from mym2.bootstrap import bootstrap
from mym2.db.engine import create_mym2_engine
from mym2.db.migrate import upgrade_to_head
from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.db.session import init_session_factory, reset_session_factory
from mym2.domain.enums import AccountType, CategoryType
from mym2.repositories.transaction_repo import TransactionFilter, TransactionRepository
from mym2.services.report_service import ReportFilter, ReportService
from mym2.ui.pages.transactions_page import TransactionsPage


def seed_synthetic_ledger(db_path: Path, rows: int = 10_000) -> None:
    """创建只含合成数据的账本。"""
    upgrade_to_head(db_path)
    engine = create_mym2_engine(db_path)
    try:
        with Session(engine) as session:
            accounts = [
                Account(
                    name=f'合成账户{i}',
                    type=AccountType.BANK.value if i % 2 else AccountType.CASH.value,
                    is_enabled=True,
                    is_editable=True,
                    opening_balance_minor=1_000_000,
                    current_balance_minor=1_000_000,
                )
                for i in range(4)
            ]
            categories = [
                Category(
                    name=f'合成分类{i}',
                    type=(
                        CategoryType.EXPENSE.value
                        if i % 3
                        else CategoryType.INCOME.value
                    ),
                    is_enabled=True,
                )
                for i in range(8)
            ]
            session.add_all(accounts + categories)
            session.flush()

            start = date(2026, 1, 1)
            txs = []
            for i in range(rows):
                category = categories[i % len(categories)]
                tx_type = 'income' if category.type == CategoryType.INCOME.value else 'expense'
                account = accounts[i % len(accounts)]
                txs.append(
                    Transaction(
                        transaction_date=start + timedelta(days=i % 365),
                        type=tx_type,
                        account_out_id=account.id,
                        account_in_id=account.id if tx_type == 'income' else None,
                        category_id=category.id,
                        amount_minor=100 + (i % 50_000),
                        note=f'synthetic-{i}',
                        source='benchmark',
                        is_cleared=i % 2 == 0,
                    )
                )
            session.add_all(txs)
            session.commit()
    finally:
        engine.dispose()


def run_benchmark(rows: int = 10_000) -> dict[str, float]:
    """运行基准并返回耗时秒数。"""
    tmpdir = Path(tempfile.mkdtemp(prefix='mym2_perf_'))
    db_path = tmpdir / 'mym2.db'
    try:
        seed_start = time.perf_counter()
        seed_synthetic_ledger(db_path, rows=rows)
        seed_seconds = time.perf_counter() - seed_start

        reset_session_factory()
        app = QApplication.instance() or QApplication([])

        startup_start = time.perf_counter()
        window = bootstrap(data_dir=tmpdir, auto_migrate=False)
        startup_seconds = time.perf_counter() - startup_start

        engine = create_mym2_engine(db_path)
        init_session_factory(engine)
        try:
            with Session(engine) as session:
                repo = TransactionRepository(session)
                filter_start = time.perf_counter()
                page = repo.query_filtered(
                    TransactionFilter(
                        date_from=date(2026, 3, 1),
                        date_to=date(2026, 9, 30),
                        types=['expense'],
                        keyword='synthetic',
                    ),
                    page=1,
                    page_size=50,
                    sort_desc=True,
                )
                filter_seconds = time.perf_counter() - filter_start

                report_start = time.perf_counter()
                monthly = ReportService().query(
                    session,
                    'monthly_income_expense',
                    ReportFilter(
                        start_date=date(2026, 1, 1),
                        end_date=date(2026, 12, 31),
                    ),
                )
                report_seconds = time.perf_counter() - report_start

            page_widget = TransactionsPage()
            ui_start = time.perf_counter()
            page_widget.refresh()
            ui_refresh_seconds = time.perf_counter() - ui_start
            page_widget.deleteLater()
        finally:
            engine.dispose()
            window.close()
            app.processEvents()

        return {
            'rows': float(rows),
            'seed_seconds': seed_seconds,
            'startup_seconds': startup_seconds,
            'filter_seconds': filter_seconds,
            'filter_total': float(page.total),
            'monthly_report_seconds': report_seconds,
            'monthly_rows': float(len(monthly.rows)),
            'transactions_page_refresh_seconds': ui_refresh_seconds,
        }
    finally:
        reset_session_factory()
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> None:
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
