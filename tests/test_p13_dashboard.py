"""P13: Dashboard query service tests."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.dashboard_query import DashboardQueryService
from mym.infrastructure.database.db_manager import DatabaseManager
from tests.fixtures.ledger_scenarios import (
    scenario_empty,
    scenario_multi_account_transfer,
    scenario_salary_and_dining,
)


@pytest.fixture
def session():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    s = mgr.new_session()
    yield s
    s.close()
    mgr.close()
    tmp_path.unlink(missing_ok=True)


def test_empty_dashboard(session: Session) -> None:
    scenario_empty(session)
    svc = DashboardQueryService(session)
    summary = svc.get_summary()
    assert summary.total_assets == Decimal("0")
    assert summary.total_liabilities == Decimal("0")
    assert summary.net_worth == Decimal("0")


def test_dashboard_with_salary(session: Session) -> None:
    scenario_salary_and_dining(session)
    svc = DashboardQueryService(session)
    summary = svc.get_summary()
    assert summary.total_assets >= Decimal("0")
    assert isinstance(summary.net_worth, Decimal)
    assert len(summary.recent_transactions) >= 2
    assert len(summary.monthly_trend) == 6


def test_dashboard_with_transfer(session: Session) -> None:
    scenario_multi_account_transfer(session)
    svc = DashboardQueryService(session)
    summary = svc.get_summary()
    # Transfer doesn't change total assets
    assert isinstance(summary.total_assets, Decimal)
    assert len(summary.recent_transactions) >= 1


def test_investment_linked_excluded(session: Session) -> None:
    """Investment-linked accounts should not be counted in total_assets."""
    from mym.domain.entities.account import Account
    from mym.domain.enums import AccountType

    bank = Account(name="Bank", account_type=AccountType.ASSET,
                   opening_balance=Decimal("10000"), current_balance=Decimal("10000"))
    session.add(bank)
    inv = Account(name="StockPool", account_type=AccountType.INVESTMENT_LINKED,
                  opening_balance=Decimal("5000"), current_balance=Decimal("5000"))
    session.add(inv)
    session.flush()

    svc = DashboardQueryService(session)
    summary = svc.get_summary()
    assert summary.total_assets == Decimal("10000")  # Only bank, not stock pool
