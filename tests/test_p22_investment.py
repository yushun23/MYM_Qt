"""Tests for P22 – Investment module basics: models, lifecycle, rollback."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.investment_service import InvestmentService
from mym.domain.entities.account import Account
from mym.domain.entities.import_ import ImportJob
from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentTrade,
    Security,
)
from mym.domain.enums import (
    AccountType,
    CashFlowType,
    ImportStatus,
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


class TestInvestmentRepository:
    def test_add_and_get_account(self, session):
        core = _make_core_account(session, "股票联动", AccountType.INVESTMENT_LINKED)
        repo = InvestmentRepository(session)
        acct = InvestmentAccount(name="券商A", linked_account_id=core.id, broker="HT")
        repo.add_account(acct)
        session.flush()

        fetched = repo.get_account(acct.id)
        assert fetched is not None
        assert fetched.name == "券商A"
        assert fetched.module_status == InvestmentModuleStatus.ENABLED

    def test_list_visible_accounts(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        repo = InvestmentRepository(session)
        a1 = InvestmentAccount(name="可见", linked_account_id=core.id, module_status=InvestmentModuleStatus.ENABLED)
        a2 = InvestmentAccount(name="隐藏", linked_account_id=core.id, module_status=InvestmentModuleStatus.HIDDEN)
        repo.add_account(a1)
        repo.add_account(a2)
        session.flush()

        visible = repo.list_visible_accounts()
        assert len(visible) == 1
        assert visible[0].name == "可见"

    def test_security_add_and_find(self, session):
        repo = InvestmentRepository(session)
        sec = Security(symbol="600519", name="贵州茅台", market="CN")
        repo.add_security(sec)
        session.flush()

        found = repo.find_security_by_symbol("600519")
        assert found is not None
        assert found.name == "贵州茅台"

    def test_trade_and_import_rollback(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        repo = InvestmentRepository(session)

        acct = InvestmentAccount(name="券商", linked_account_id=core.id)
        repo.add_account(acct)
        session.flush()

        sec = Security(symbol="000001", name="平安银行")
        repo.add_security(sec)
        session.flush()

        job = ImportJob(source_file="test.csv", import_type="broker", status=ImportStatus.COMPLETED)
        session.add(job)
        session.flush()

        trade = InvestmentTrade(
            investment_account_id=acct.id, security_id=sec.id,
            trade_date=date(2025, 7, 1), trade_type="buy",
            quantity=Decimal("100"), price=Decimal("50"),
            amount=Decimal("5000"), net_amount=Decimal("5000"),
            import_job_id=job.id,
        )
        repo.add_trade(trade)
        session.flush()

        # Rollback
        deleted = repo.delete_trades_by_import(job.id)
        assert deleted == 1

        trades = repo.list_trades(acct.id)
        assert len(trades) == 0

    def test_cash_flow_net_calculation(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        repo = InvestmentRepository(session)

        acct = InvestmentAccount(name="券商", linked_account_id=core.id)
        repo.add_account(acct)
        session.flush()

        cf1 = InvestmentCashFlow(
            investment_account_id=acct.id,
            flow_date=date(2025, 7, 5), flow_type=CashFlowType.TRANSFER_IN,
            amount=Decimal("10000"),
        )
        cf2 = InvestmentCashFlow(
            investment_account_id=acct.id,
            flow_date=date(2025, 7, 15), flow_type=CashFlowType.TRANSFER_OUT,
            amount=Decimal("-2000"),
        )
        repo.add_cash_flow(cf1)
        repo.add_cash_flow(cf2)
        session.flush()

        net = repo.get_net_cash_flow(acct.id, 2025, 7)
        assert net == Decimal("8000")


class TestInvestmentService:
    def test_create_account(self, session):
        core = _make_core_account(session, "股票联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)

        result = svc.create_account(
            "券商A", core.id, broker="HT",
            initial_capital=Decimal("100000"),
        )
        assert result.success
        assert result.entity_id is not None

    def test_create_account_wrong_type(self, session):
        core = _make_core_account(session, "普通账户", AccountType.ASSET)
        svc = InvestmentService(session)

        result = svc.create_account("券商A", core.id)
        assert not result.success
        assert "investment_linked" in str(result.errors).lower()

    def test_hide_and_show(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)
        result = svc.create_account("券商A", core.id)
        acct_id = result.entity_id

        # Hide
        r = svc.hide_account(acct_id)
        assert r.success

        repo = InvestmentRepository(session)
        acct = repo.get_account(acct_id)
        assert acct.module_status == InvestmentModuleStatus.HIDDEN

        # Show
        r = svc.show_account(acct_id)
        assert r.success
        acct = repo.get_account(acct_id)
        assert acct.module_status == InvestmentModuleStatus.ENABLED

    def test_archive(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)
        result = svc.create_account("券商A", core.id)

        r = svc.archive_account(result.entity_id)
        assert r.success

        repo = InvestmentRepository(session)
        acct = repo.get_account(result.entity_id)
        assert acct.module_status == InvestmentModuleStatus.ARCHIVED
        assert acct.is_archived

    def test_permanent_delete_requires_confirmation(self, session):
        core = _make_core_account(session, "联动", AccountType.INVESTMENT_LINKED)
        svc = InvestmentService(session)
        result = svc.create_account("券商A", core.id)

        # No backup
        r = svc.permanent_delete_with_confirmation(result.entity_id, False, True)
        assert not r.success

        # No confirmation
        r = svc.permanent_delete_with_confirmation(result.entity_id, True, False)
        assert not r.success

        # Both satisfied
        r = svc.permanent_delete_with_confirmation(result.entity_id, True, True)
        assert r.success

        repo = InvestmentRepository(session)
        session.flush()
        assert repo.get_account(result.entity_id) is None


