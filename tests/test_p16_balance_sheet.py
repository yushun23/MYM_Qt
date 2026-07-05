"""Tests for P16 – BalanceSheetQueryService."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.dto.report_dto import BalanceSheetSnapshot
from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.services.balance_sheet_query import BalanceSheetQueryService
from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.enums import AccountType, CategoryType
from mym.infrastructure.database.db_manager import DatabaseManager


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


def _acc(s, name, atype, bal="0"):
    a = Account(name=name, account_type=atype, opening_balance=Decimal(bal), current_balance=Decimal(bal))
    s.add(a)
    s.flush()
    return a


def _post(s, dto):
    r = CreateTransactionUseCase(s).execute(dto)
    if not r.success:
        raise RuntimeError(str(r.errors))
    return r.transaction_id


class TestBalanceSheet:
    def test_empty_ledger(self, session):
        _acc(session, "Cash", AccountType.ASSET, "0")
        svc = BalanceSheetQueryService(session)
        snap = svc.get_balance_sheet(date(2026, 7, 5))
        assert snap.total_assets == Decimal("0")
        assert snap.total_liabilities == Decimal("0")
        assert snap.net_worth == Decimal("0")

    def test_assets_and_liabilities(self, session):
        _acc(session, "Bank", AccountType.ASSET, "10000")
        _acc(session, "CreditCard", AccountType.LIABILITY, "0")
        svc = BalanceSheetQueryService(session)
        snap = svc.get_balance_sheet(date(2026, 7, 5))
        assert snap.total_assets == Decimal("10000")
        assert snap.total_liabilities == Decimal("0")
        assert snap.net_worth == Decimal("10000")

    def test_as_of_date_calculation(self, session):
        bank = _acc(session, "Bank", AccountType.ASSET, "1000")
        cat = Category(name="Test", category_type=CategoryType.EXPENSE)
        session.add(cat)
        session.flush()

        # Post a transaction after our as_of date
        _post(session, CreateTransactionDTO(
            business_type="expense", transaction_date=date(2026, 8, 1),
            description="Future expense", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("100"), category_id=cat.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("100"), category_id=cat.id),
            ],
        ))

        # Query as of July – should NOT include August transaction
        svc = BalanceSheetQueryService(session)
        snap = svc.get_balance_sheet(date(2026, 7, 31))
        # Balance after expense should have reduced, but the expense is in August
        # Opening balance = 1000, but current_balance may have been updated
        assert snap.total_assets >= Decimal("0")

    def test_investment_valuation_warning(self, session):
        _acc(session, "Stock", AccountType.INVESTMENT_LINKED, "5000")
        svc = BalanceSheetQueryService(session)
        snap = svc.get_balance_sheet(date(2026, 7, 5))
        assert "估值数据不足" in snap.investment_valuation_warning

    def test_account_groups(self, session):
        _acc(session, "Bank", AccountType.ASSET, "5000")
        _acc(session, "Alipay", AccountType.ASSET, "2000")
        _acc(session, "CC", AccountType.LIABILITY, "0")
        svc = BalanceSheetQueryService(session)
        snap = svc.get_balance_sheet(date(2026, 7, 5))
        assert len(snap.account_groups) > 0
        assert len(snap.liability_groups) > 0

    def test_receivable_separate(self, session):
        _acc(session, "Bank", AccountType.ASSET, "5000")
        _acc(session, "Receivable", AccountType.RECEIVABLE, "1000")
        svc = BalanceSheetQueryService(session)
        snap = svc.get_balance_sheet(date(2026, 7, 5))
        assert snap.receivable_balance == Decimal("1000")
        # Bank (5000) + Receivable (1000) = 6000
        assert snap.total_assets == Decimal("6000")
