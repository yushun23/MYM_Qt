"""Tests for P18 – ReceivableService and ReceivableRepository."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.services.receivable_service import ReceivableService
from mym.domain.entities.account import Account
from mym.domain.entities.receivable import ReceivableCase, ReceivableEvent
from mym.domain.enums import AccountType, ReceivableStatus
from mym.infrastructure.database.db_manager import DatabaseManager
from mym.infrastructure.repositories.receivable_repo import ReceivableRepository
from mym.infrastructure.repositories.account_repo import AccountRepository


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


class TestReceivableRepository:
    def test_add_and_get_case(self, session):
        receivable_acc = _acc(session, "应收", AccountType.RECEIVABLE, "0")
        case = ReceivableCase(
            account_id=receivable_acc.id, debtor="张三", total_amount=Decimal("1000"),
            status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1),
        )
        repo = ReceivableRepository(session)
        repo.add_case(case)
        session.flush()

        fetched = repo.get_by_id(case.id)
        assert fetched is not None
        assert fetched.debtor == "张三"
        assert fetched.outstanding_amount == Decimal("1000")

    def test_list_by_account(self, session):
        acc1 = _acc(session, "应收A", AccountType.RECEIVABLE, "0")
        acc2 = _acc(session, "应收B", AccountType.RECEIVABLE, "0")
        repo = ReceivableRepository(session)

        c1 = ReceivableCase(account_id=acc1.id, debtor="甲", total_amount=Decimal("100"),
                           status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1))
        c2 = ReceivableCase(account_id=acc2.id, debtor="乙", total_amount=Decimal("200"),
                           status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1))
        repo.add_case(c1)
        repo.add_case(c2)
        session.flush()

        cases = repo.list_by_account(acc1.id)
        assert len(cases) == 1
        assert cases[0].debtor == "甲"

    def test_add_event(self, session):
        acc = _acc(session, "应收", AccountType.RECEIVABLE, "0")
        repo = ReceivableRepository(session)
        case = ReceivableCase(account_id=acc.id, debtor="李四", total_amount=Decimal("500"),
                             status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1))
        repo.add_case(case)
        session.flush()

        event = ReceivableEvent(case_id=case.id, event_type="advance",
                               event_date=date(2026, 7, 1), amount=Decimal("500"))
        repo.add_event(event)
        session.flush()

        events = repo.get_events(case.id)
        assert len(events) == 1
        assert events[0].event_type == "advance"

    def test_update_case_amounts_partial(self, session):
        acc = _acc(session, "应收", AccountType.RECEIVABLE, "0")
        repo = ReceivableRepository(session)
        case = ReceivableCase(account_id=acc.id, debtor="王五", total_amount=Decimal("1000"),
                             status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1))
        repo.add_case(case)
        session.flush()

        repo.update_case_amounts(case.id, recovered_delta=Decimal("300"))
        session.flush()

        fetched = repo.get_by_id(case.id)
        assert fetched.recovered_amount == Decimal("300")
        assert fetched.status == ReceivableStatus.PARTIALLY_RECOVERED

    def test_update_case_amounts_full(self, session):
        acc = _acc(session, "应收", AccountType.RECEIVABLE, "0")
        repo = ReceivableRepository(session)
        case = ReceivableCase(account_id=acc.id, debtor="赵六", total_amount=Decimal("500"),
                             status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1))
        repo.add_case(case)
        session.flush()

        repo.update_case_amounts(case.id, recovered_delta=Decimal("500"))
        session.flush()

        fetched = repo.get_by_id(case.id)
        assert fetched.status == ReceivableStatus.FULLY_RECOVERED

    def test_list_active(self, session):
        acc = _acc(session, "应收", AccountType.RECEIVABLE, "0")
        repo = ReceivableRepository(session)

        pending = ReceivableCase(account_id=acc.id, debtor="P", total_amount=Decimal("100"),
                                status=ReceivableStatus.PENDING, occurrence_date=date(2026, 7, 1))
        done = ReceivableCase(account_id=acc.id, debtor="D", total_amount=Decimal("100"),
                             status=ReceivableStatus.FULLY_RECOVERED,
                             recovered_amount=Decimal("100"), occurrence_date=date(2026, 7, 1))
        repo.add_case(pending)
        repo.add_case(done)
        session.flush()

        active = repo.list_active()
        assert len(active) == 1
        assert active[0].debtor == "P"


class TestReceivableService:
    @pytest.fixture
    def seeded_session(self, session):
        """Create a session with asset and receivable accounts."""
        _acc(session, "Bank", AccountType.ASSET, "10000")
        _acc(session, "应收", AccountType.RECEIVABLE, "0")
        return session

    def test_create_advance(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        result = svc.create_advance(
            account_id=rec_accs[0].id, debtor="测试人",
            amount=Decimal("500"), occurrence_date=date(2026, 7, 1),
            notes="测试垫付",
        )
        seeded_session.flush()
        assert result.success
        assert result.case_id is not None
        assert result.transaction_id is not None

        # Verify the receivable case
        repo = ReceivableRepository(seeded_session)
        case = repo.get_by_id(result.case_id)
        assert case.debtor == "测试人"
        assert case.total_amount == Decimal("500")
        assert case.status == ReceivableStatus.PENDING

    def test_partial_recovery(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        adv = svc.create_advance(
            account_id=rec_accs[0].id, debtor="测试人",
            amount=Decimal("1000"), occurrence_date=date(2026, 7, 1),
        )
        seeded_session.flush()

        rec = svc.recover(
            case_id=adv.case_id, amount=Decimal("400"),
            event_date=date(2026, 7, 15),
        )
        seeded_session.flush()
        assert rec.success

        repo = ReceivableRepository(seeded_session)
        case = repo.get_by_id(adv.case_id)
        assert case.status == ReceivableStatus.PARTIALLY_RECOVERED
        assert case.recovered_amount == Decimal("400")
        assert case.outstanding_amount == Decimal("600")

    def test_full_recovery(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        adv = svc.create_advance(
            account_id=rec_accs[0].id, debtor="测试人",
            amount=Decimal("500"), occurrence_date=date(2026, 7, 1),
        )
        seeded_session.flush()

        rec = svc.recover(
            case_id=adv.case_id, amount=Decimal("500"),
            event_date=date(2026, 7, 20),
        )
        seeded_session.flush()
        assert rec.success

        repo = ReceivableRepository(seeded_session)
        case = repo.get_by_id(adv.case_id)
        assert case.status == ReceivableStatus.FULLY_RECOVERED

    def test_over_recovery_rejected(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        adv = svc.create_advance(
            account_id=rec_accs[0].id, debtor="测试人",
            amount=Decimal("300"), occurrence_date=date(2026, 7, 1),
        )
        seeded_session.flush()

        rec = svc.recover(
            case_id=adv.case_id, amount=Decimal("500"),
            event_date=date(2026, 7, 15),
        )
        assert not rec.success

    def test_write_off(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        adv = svc.create_advance(
            account_id=rec_accs[0].id, debtor="坏账人",
            amount=Decimal("200"), occurrence_date=date(2026, 7, 1),
        )
        seeded_session.flush()

        wo = svc.write_off(
            case_id=adv.case_id, amount=Decimal("200"),
            event_date=date(2026, 8, 1),
        )
        seeded_session.flush()
        assert wo.success

        repo = ReceivableRepository(seeded_session)
        case = repo.get_by_id(adv.case_id)
        assert case.status == ReceivableStatus.WRITTEN_OFF

    def test_unrecovered_report(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        svc.create_advance(
            account_id=rec_accs[0].id, debtor="A",
            amount=Decimal("100"), occurrence_date=date(2026, 7, 1),
        )
        svc.create_advance(
            account_id=rec_accs[0].id, debtor="B",
            amount=Decimal("200"), occurrence_date=date(2026, 7, 2),
        )
        seeded_session.flush()

        report = svc.get_unrecovered_report()
        assert len(report) == 2

    def test_recover_on_done_case_rejected(self, seeded_session):
        acc_repo = AccountRepository(seeded_session)
        rec_accs = acc_repo.list_by_type(AccountType.RECEIVABLE)
        svc = ReceivableService(seeded_session)

        adv = svc.create_advance(
            account_id=rec_accs[0].id, debtor="X",
            amount=Decimal("100"), occurrence_date=date(2026, 7, 1),
        )
        seeded_session.flush()
        svc.recover(case_id=adv.case_id, amount=Decimal("100"), event_date=date(2026, 7, 10))
        seeded_session.flush()

        # Try recovering again
        rec = svc.recover(case_id=adv.case_id, amount=Decimal("50"), event_date=date(2026, 7, 20))
        assert not rec.success
