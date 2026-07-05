"""Tests for investment module – historical archive & lifecycle (no stock trading via P23-P28)."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.investment_service import InvestmentService
from mym.domain.entities.account import Account
from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentTrade,
    Security,
)
from mym.domain.enums import (
    AccountType,
    CashFlowType,
    InvestmentModuleStatus,
)
from mym.infrastructure.database.db_manager import DatabaseManager
from mym.infrastructure.repositories.investment_repo import InvestmentRepository


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


def _make_core_account(session, name, atype):
    acct = Account(name=name, account_type=atype, opening_balance=Decimal("0"), current_balance=Decimal("0"))
    session.add(acct)
    session.flush()
    return acct


def _setup_investment_account(session) -> InvestmentAccount:
    core = _make_core_account(session, "股票联动", AccountType.INVESTMENT_LINKED)
    svc = InvestmentService(session)
    result = svc.create_account("券商A", core.id, initial_capital=Decimal("100000"))
    session.flush()
    return InvestmentRepository(session).get_account(result.entity_id)


class TestHistoricalArchive:
    """Investment accounts and trades should persist as read-only historical snapshots."""

    def test_account_creation_and_lifecycle(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)

        result = svc.create_account("券商历史", core.id, broker="HT", initial_capital=Decimal("50000"))
        assert result.success
        acct_id = result.entity_id

        # Verify repository read
        repo = InvestmentRepository(session)
        acct = repo.get_account(acct_id)
        assert acct is not None
        assert acct.name == "券商历史"
        assert acct.broker == "HT"

    def test_archive_then_read(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)
        result = svc.create_account("券商A", core.id)
        acct_id = result.entity_id

        # Archive
        r = svc.archive_account(acct_id)
        assert r.success

        repo = InvestmentRepository(session)
        acct = repo.get_account(acct_id)
        assert acct.module_status == InvestmentModuleStatus.ARCHIVED
        assert acct.is_archived

    def test_hide_and_show(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)
        result = svc.create_account("券商A", core.id)
        acct_id = result.entity_id

        svc.hide_account(acct_id)
        repo = InvestmentRepository(session)
        acct = repo.get_account(acct_id)
        assert acct.module_status == InvestmentModuleStatus.HIDDEN

        svc.show_account(acct_id)
        acct = repo.get_account(acct_id)
        assert acct.module_status == InvestmentModuleStatus.ENABLED

    def test_historical_trades_persist(self, session):
        """Historical trades should be storable and retrievable."""
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        repo = InvestmentRepository(session)

        acct = InvestmentAccount(name="券商历史", linked_account_id=core.id)
        repo.add_account(acct)
        session.flush()

        sec = Security(symbol="600519", name="贵州茅台", market="CN")
        repo.add_security(sec)
        session.flush()

        trade = InvestmentTrade(
            investment_account_id=acct.id, security_id=sec.id,
            trade_date=date(2025, 7, 1), trade_type="buy",
            quantity=Decimal("100"), price=Decimal("50"),
            amount=Decimal("5000"), net_amount=Decimal("5000"),
        )
        repo.add_trade(trade)
        session.flush()

        trades = repo.list_trades(account_id=acct.id)
        assert len(trades) == 1
        assert trades[0].trade_type == "buy"
        assert trades[0].quantity == Decimal("100")

    def test_historical_cash_flows(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        repo = InvestmentRepository(session)

        acct = InvestmentAccount(name="券商历史", linked_account_id=core.id)
        repo.add_account(acct)
        session.flush()

        cf1 = InvestmentCashFlow(
            investment_account_id=acct.id,
            flow_date=date(2025, 7, 5), flow_type=CashFlowType.TRANSFER_IN,
            amount=Decimal("10000"),
        )
        cf2 = InvestmentCashFlow(
            investment_account_id=acct.id,
            flow_date=date(2025, 7, 15), flow_type=CashFlowType.DIVIDEND,
            amount=Decimal("500"),
        )
        repo.add_cash_flow(cf1)
        repo.add_cash_flow(cf2)
        session.flush()

        cfs = repo.list_cash_flows(account_id=acct.id)
        assert len(cfs) == 2

        net = repo.get_net_cash_flow(acct.id, 2025, 7)
        assert net == Decimal("10500")

    def test_security_reference(self, session):
        """Security master data should be queryable for historical reference."""
        repo = InvestmentRepository(session)
        sec = Security(symbol="000001", name="平安银行", market="CN")
        repo.add_security(sec)
        session.flush()

        found = repo.find_security_by_symbol("000001")
        assert found is not None
        assert found.name == "平安银行"

        all_sec = repo.list_securities()
        assert len(all_sec) == 1
