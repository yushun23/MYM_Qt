"""Tests for P15 – ReportQueryService."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.dto.report_dto import ReportPeriodDTO
from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.services.report_query import ReportQueryService
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


def _make_acc(s, name, atype, bal="0"):
    a = Account(name=name, account_type=atype, opening_balance=Decimal(bal), current_balance=Decimal(bal))
    s.add(a)
    s.flush()
    return a


def _make_cat(s, name, ctype):
    c = Category(name=name, category_type=ctype)
    s.add(c)
    s.flush()
    return c


def _post(s, dto):
    r = CreateTransactionUseCase(s).execute(dto)
    if not r.success:
        raise RuntimeError(str(r.errors))
    return r.transaction_id


class TestReportQueryService:
    def test_empty_period(self, session):
        _make_acc(session, "Cash", AccountType.ASSET, "10000")
        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2099, 1, 1), date(2099, 12, 31))
        summary = svc.get_income_expense_report(period)
        assert summary.total_income == 0
        assert summary.total_expense == 0
        assert summary.net_balance == 0
        assert summary.transaction_count == 0

    def test_income_and_expense_totals(self, session):
        bank = _make_acc(session, "Bank", AccountType.ASSET, "10000")
        inc_cat = _make_cat(session, "Salary", CategoryType.INCOME)
        exp_cat = _make_cat(session, "Food", CategoryType.EXPENSE)

        _post(session, CreateTransactionDTO(
            business_type="income", transaction_date=date(2026, 7, 1),
            description="Salary", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("5000"), category_id=inc_cat.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("5000"), category_id=inc_cat.id),
            ],
        ))
        _post(session, CreateTransactionDTO(
            business_type="expense", transaction_date=date(2026, 7, 5),
            description="Lunch", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("200"), category_id=exp_cat.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("200"), category_id=exp_cat.id),
            ],
        ))

        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2026, 7, 1), date(2026, 7, 31))
        summary = svc.get_income_expense_report(period)
        assert summary.total_income == Decimal("5000")
        assert summary.total_expense == Decimal("200")
        assert summary.net_balance == Decimal("4800")
        assert summary.transaction_count == 2

    def test_net_balance_formula(self, session):
        bank = _make_acc(session, "Bank", AccountType.ASSET, "0")
        cat = _make_cat(session, "Misc", CategoryType.INCOME)
        _post(session, CreateTransactionDTO(
            business_type="income", transaction_date=date(2026, 8, 1),
            description="Income", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("1000"), category_id=cat.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("1000"), category_id=cat.id),
            ],
        ))
        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2026, 1, 1), date(2026, 12, 31))
        summary = svc.get_income_expense_report(period)
        assert summary.net_balance == summary.total_income - summary.total_expense

    def test_transfer_excluded_from_stats(self, session):
        bank_a = _make_acc(session, "A", AccountType.ASSET, "1000")
        bank_b = _make_acc(session, "B", AccountType.ASSET, "0")

        _post(session, CreateTransactionDTO(
            business_type="transfer", transaction_date=date(2026, 7, 1),
            description="Move money", lines=[
                TransactionLineDTO(account_id=bank_b.id, role="debit", signed_amount=Decimal("500")),
                TransactionLineDTO(account_id=bank_a.id, role="credit", signed_amount=Decimal("500")),
            ],
        ))

        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2026, 7, 1), date(2026, 7, 31))
        summary = svc.get_income_expense_report(period)
        assert summary.transaction_count == 0

    def test_monthly_trend_has_months(self, session):
        bank = _make_acc(session, "Bank", AccountType.ASSET, "10000")
        cat = _make_cat(session, "Salary", CategoryType.INCOME)

        for m in range(1, 7):
            _post(session, CreateTransactionDTO(
                business_type="income", transaction_date=date(2026, m, 15),
                description=f"Month {m}", lines=[
                    TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("1000"), category_id=cat.id),
                    TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("1000"), category_id=cat.id),
                ],
            ))

        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2026, 1, 1), date(2026, 6, 30))
        summary = svc.get_income_expense_report(period)
        assert len(summary.monthly_trend) == 6

    def test_category_breakdown(self, session):
        bank = _make_acc(session, "Bank", AccountType.ASSET, "10000")
        food = _make_cat(session, "Food", CategoryType.EXPENSE)
        transport = _make_cat(session, "Transport", CategoryType.EXPENSE)

        _post(session, CreateTransactionDTO(
            business_type="expense", transaction_date=date(2026, 7, 1),
            description="Meal", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("100"), category_id=food.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("100"), category_id=food.id),
            ],
        ))
        _post(session, CreateTransactionDTO(
            business_type="expense", transaction_date=date(2026, 7, 2),
            description="Bus", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("50"), category_id=transport.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("50"), category_id=transport.id),
            ],
        ))

        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2026, 7, 1), date(2026, 7, 31))
        summary = svc.get_income_expense_report(period)
        names = {c["name"] for c in summary.category_breakdown_expense}
        assert "Food" in names
        assert "Transport" in names

    def test_transaction_details_present(self, session):
        bank = _make_acc(session, "Bank", AccountType.ASSET, "10000")
        cat = _make_cat(session, "Salary", CategoryType.INCOME)
        _post(session, CreateTransactionDTO(
            business_type="income", transaction_date=date(2026, 7, 1),
            description="Pay", lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("1000"), category_id=cat.id),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("1000"), category_id=cat.id),
            ],
        ))
        svc = ReportQueryService(session)
        period = ReportPeriodDTO(date(2026, 7, 1), date(2026, 7, 31))
        summary = svc.get_income_expense_report(period)
        assert len(summary.transaction_details) == 1
        assert summary.transaction_details[0]["business_type"] == "income"
        assert summary.transaction_details[0]["description"] == "Pay"
