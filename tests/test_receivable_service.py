"""ReceivableService 集成测试。

覆盖：垫付/还款创建、余额重算、删除、验证规则、待收状态准确性。
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from mym2.db.engine import create_mym2_engine
from mym2.db.ensure_schema import ensure_budget_columns
from mym2.db.migrate import set_alembic_ini_path, upgrade_to_head
from mym2.db.models import Account
from mym2.db.session import (
    get_session,
    init_session_factory,
    remove_session,
    reset_session_factory,
)
from mym2.domain.enums import AccountType, TransactionType
from mym2.services.balance_service import BalanceService
from mym2.services.ledger_service import LedgerService
from mym2.services.receivable_service import (
    AdvanceDTO,
    ReceivableService,
    RepayDTO,
)

ALEMBIC_INI = Path(__file__).resolve().parent.parent / 'alembic.ini'


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_session() -> None:
    yield
    remove_session()
    reset_session_factory()


@pytest.fixture
def temp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix='.db', prefix='mym2_test_')
    import os
    os.close(fd)
    yield Path(path)
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def migrated_db(temp_db: Path) -> Path:
    set_alembic_ini_path(str(ALEMBIC_INI))
    upgrade_to_head(temp_db)
    reset_session_factory()
    engine = create_mym2_engine(temp_db)
    ensure_budget_columns(engine)
    init_session_factory(engine)
    yield temp_db
    remove_session()
    reset_session_factory()
    engine.dispose()


@pytest.fixture
def svc() -> ReceivableService:
    return ReceivableService()


@pytest.fixture
def balance_svc() -> BalanceService:
    return BalanceService()


@pytest.fixture
def cash_account(migrated_db: Path) -> Account:
    session = get_session()
    acct = Account(
        name='现金',
        type=AccountType.CASH,
        is_enabled=True,
        is_editable=True,
        opening_balance_minor=1000000,  # 10000 元
        current_balance_minor=1000000,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


@pytest.fixture
def bank_account(migrated_db: Path) -> Account:
    session = get_session()
    acct = Account(
        name='银行储蓄',
        type=AccountType.BANK,
        is_enabled=True,
        is_editable=True,
        opening_balance_minor=500000,
        current_balance_minor=500000,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


@pytest.fixture
def receivable_account(migrated_db: Path) -> Account:
    """创建一个应收账户（债务人）。"""
    session = get_session()
    acct = Account(
        name='张三',
        type=AccountType.RECEIVABLE,
        is_enabled=True,
        is_editable=True,
        opening_balance_minor=0,
        current_balance_minor=0,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


@pytest.fixture
def receivable_account2(migrated_db: Path) -> Account:
    session = get_session()
    acct = Account(
        name='李四',
        type=AccountType.RECEIVABLE,
        is_enabled=True,
        is_editable=True,
        opening_balance_minor=0,
        current_balance_minor=0,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


# ═══════════════════════════════════════════════════════
#  Tests
# ═══════════════════════════════════════════════════════


class TestAdvance:
    """垫付测试。"""

    def test_advance_from_cash(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        receivable_account: Account,
    ) -> None:
        """从现金账户向债务人垫付。"""
        session = get_session()
        dto = AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=20000,  # 200 元
            transaction_date=date(2026, 7, 1),
            note='借给张三',
        )
        tx = svc.advance(session, dto)
        session.commit()

        assert tx.type == TransactionType.RECEIVABLE_ADVANCE
        assert tx.account_out_id == cash_account.id
        assert tx.account_in_id == receivable_account.id
        assert tx.amount_minor == 20000

        session.refresh(receivable_account)
        session.refresh(cash_account)
        assert receivable_account.current_balance_minor == 20000
        assert cash_account.current_balance_minor == 980000  # 1000000 - 20000

    def test_advance_from_bank(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        bank_account: Account,
        receivable_account: Account,
    ) -> None:
        """从银行账户向债务人垫付。"""
        session = get_session()
        dto = AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=bank_account.id,
            amount_minor=50000,
            transaction_date=date(2026, 7, 2),
            note='预支差旅费',
        )
        svc.advance(session, dto)
        session.commit()

        session.refresh(receivable_account)
        session.refresh(bank_account)
        assert receivable_account.current_balance_minor == 50000
        assert bank_account.current_balance_minor == 450000  # 500000 - 50000

    def test_advance_invalid_debtor_type(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        bank_account: Account,
        cash_account: Account,
    ) -> None:
        """向非 receivable 类型账户垫付应被拒绝。"""
        session = get_session()
        dto = AdvanceDTO(
            debtor_account_id=bank_account.id,  # bank, not receivable
            funding_account_id=cash_account.id,
            amount_minor=10000,
            transaction_date=date(2026, 7, 3),
        )
        with pytest.raises(ValueError, match='不是应收'):
            svc.advance(session, dto)

    def test_advance_funding_is_receivable(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        receivable_account: Account,
        receivable_account2: Account,
    ) -> None:
        """使用应收账户作为资金来源应被拒绝。"""
        session = get_session()
        dto = AdvanceDTO(
            debtor_account_id=receivable_account2.id,
            funding_account_id=receivable_account.id,  # receivable!
            amount_minor=10000,
            transaction_date=date(2026, 7, 3),
        )
        with pytest.raises(ValueError, match='不能是应收'):
            svc.advance(session, dto)


class TestRepay:
    """还款测试。"""

    def test_full_repayment(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
    ) -> None:
        """全部还款后应收余额归零。"""
        session = get_session()

        # 先垫付 30000 分
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=30000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 30000

        # 全部还款
        svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account.id,
            collection_account_id=bank_account.id,
            amount_minor=30000,
            transaction_date=date(2026, 7, 15),
            note='张三还款',
        ))
        session.commit()

        session.refresh(receivable_account)
        session.refresh(bank_account)
        assert receivable_account.current_balance_minor == 0
        assert bank_account.current_balance_minor == 530000  # 500000 + 30000

    def test_partial_repayment(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
    ) -> None:
        """部分还款后应收余额减少但未归零。"""
        session = get_session()

        # 垫付 50000 分
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=50000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        # 部分还款 30000 分
        svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account.id,
            collection_account_id=bank_account.id,
            amount_minor=30000,
            transaction_date=date(2026, 7, 10),
        ))
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 20000

    def test_repay_exceeds_balance(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
    ) -> None:
        """还款金额超过应收余额应被拒绝。"""
        session = get_session()
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=10000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        with pytest.raises(ValueError, match='超过当前应收余额'):
            svc.repay(session, RepayDTO(
                debtor_account_id=receivable_account.id,
                collection_account_id=bank_account.id,
                amount_minor=20000,  # 超过 10000
                transaction_date=date(2026, 7, 10),
            ))

    def test_repay_to_receivable(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        receivable_account: Account,
        receivable_account2: Account,
    ) -> None:
        """还款到应收账户应被拒绝。"""
        session = get_session()
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=10000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        with pytest.raises(ValueError, match='不能是应收'):
            svc.repay(session, RepayDTO(
                debtor_account_id=receivable_account.id,
                collection_account_id=receivable_account2.id,  # 另一个应收
                amount_minor=5000,
                transaction_date=date(2026, 7, 10),
            ))


class TestDelete:
    """删除应收流水测试。"""

    def test_delete_advance_restores_balance(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        receivable_account: Account,
    ) -> None:
        """删除垫付后应收余额归零。"""
        session = get_session()
        tx = svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=30000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 30000

        svc.delete_receivable_transaction(session, tx.id)
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 0

    def test_delete_repayment_restores_balance(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
    ) -> None:
        """删除还款后应收余额恢复。"""
        session = get_session()
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=50000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        tx_repay = svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account.id,
            collection_account_id=bank_account.id,
            amount_minor=20000,
            transaction_date=date(2026, 7, 10),
        ))
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 30000

        svc.delete_receivable_transaction(session, tx_repay.id)
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 50000

    def test_delete_non_receivable_transaction(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
    ) -> None:
        """删除非应收类型流水应被拒绝。"""
        from mym2.services.dto import CreateTransactionDTO

        session = get_session()
        ledger = LedgerService()
        tx = ledger.create_transaction(session, CreateTransactionDTO(
            transaction_type=TransactionType.BALANCE_ADJUSTMENT,
            transaction_date=date(2026, 7, 1),
            account_out_id=cash_account.id,
            amount_minor=1000,
        ))
        session.commit()

        with pytest.raises(ValueError, match='不是应收相关'):
            svc.delete_receivable_transaction(session, tx.id)


class TestQueries:
    """查询测试。"""

    def test_receivable_accounts_list(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        receivable_account: Account,
        receivable_account2: Account,
    ) -> None:
        session = get_session()
        accounts = svc.get_receivable_accounts(session)
        assert len(accounts) == 2
        names = {a.name for a in accounts}
        assert '张三' in names
        assert '李四' in names

    def test_receivable_balance(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        receivable_account: Account,
    ) -> None:
        session = get_session()
        balance = svc.get_receivable_balance(session, receivable_account.id)
        assert balance == 0

        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=50000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        balance = svc.get_receivable_balance(session, receivable_account.id)
        assert balance == 50000

    def test_pending_receivables(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
        receivable_account2: Account,
    ) -> None:
        """pending 只返回有余额的债务人。"""
        session = get_session()

        # 张三垫付 → 有余额
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=30000,
            transaction_date=date(2026, 7, 1),
        ))
        # 李四垫付后还清 → 无余额
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account2.id,
            funding_account_id=cash_account.id,
            amount_minor=20000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account2.id,
            collection_account_id=bank_account.id,
            amount_minor=20000,
            transaction_date=date(2026, 7, 10),
        ))
        session.commit()

        pending = svc.get_pending_receivables(session)
        assert len(pending) == 1
        assert pending[0].account_name == '张三'
        assert pending[0].balance_minor == 30000

    def test_all_summaries(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
        receivable_account2: Account,
    ) -> None:
        session = get_session()
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=50000,
            transaction_date=date(2026, 7, 1),
        ))
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account2.id,
            funding_account_id=cash_account.id,
            amount_minor=30000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account.id,
            collection_account_id=bank_account.id,
            amount_minor=20000,
            transaction_date=date(2026, 7, 10),
        ))
        session.commit()

        summaries = svc.get_all_receivable_summaries(session)
        assert len(summaries) == 2

        # 张三: 50000 垫付, 20000 还款, 余额 30000
        zs = next(s for s in summaries if s.account_name == '张三')
        assert zs.total_advanced_minor == 50000
        assert zs.total_repaid_minor == 20000
        assert zs.balance_minor == 30000

        # 李四: 30000 垫付, 0 还款, 余额 30000
        ls = next(s for s in summaries if s.account_name == '李四')
        assert ls.total_advanced_minor == 30000
        assert ls.total_repaid_minor == 0
        assert ls.balance_minor == 30000

    def test_build_transaction_views(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        cash_account: Account,
        receivable_account: Account,
    ) -> None:
        session = get_session()
        txs = svc.get_receivable_transactions(session)
        views = svc.build_transaction_views(session, txs)
        assert isinstance(views, list)

        # 垫付后应有 1 条
        svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=10000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        txs = svc.get_receivable_transactions(session)
        views = svc.build_transaction_views(session, txs)
        assert len(views) == 1
        assert views[0].debtor_account_name == '张三'
        assert views[0].counter_account_name == '现金'
        assert views[0].is_advance is True


class TestBalanceAccuracy:
    """余额准确性测试（多次操作后重算验证）。"""

    def test_multi_advance_repay_balance(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        balance_svc: BalanceService,
        cash_account: Account,
        bank_account: Account,
        receivable_account: Account,
    ) -> None:
        """多次垫付和还款后，余额与逐笔重算一致。"""
        session = get_session()

        # 垫付 3 次
        for amt, d in [(10000, 1), (20000, 2), (5000, 3)]:
            svc.advance(session, AdvanceDTO(
                debtor_account_id=receivable_account.id,
                funding_account_id=cash_account.id,
                amount_minor=amt,
                transaction_date=date(2026, 7, d),
            ))
        session.commit()

        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == 35000

        # 还款 2 次
        svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account.id,
            collection_account_id=bank_account.id,
            amount_minor=15000,
            transaction_date=date(2026, 7, 10),
        ))
        svc.repay(session, RepayDTO(
            debtor_account_id=receivable_account.id,
            collection_account_id=bank_account.id,
            amount_minor=10000,
            transaction_date=date(2026, 7, 15),
        ))
        session.commit()

        # 重算验证
        recalc = balance_svc.recalculate_account(
            session, receivable_account.id
        )
        session.refresh(receivable_account)
        assert receivable_account.current_balance_minor == recalc
        assert recalc == 10000  # 35000 - 25000

    def test_delete_then_balance_still_accurate(
        self,
        migrated_db: Path,
        svc: ReceivableService,
        balance_svc: BalanceService,
        cash_account: Account,
        receivable_account: Account,
    ) -> None:
        """删除垫付后余额准确。"""
        session = get_session()

        tx1 = svc.advance(session, AdvanceDTO(
            debtor_account_id=receivable_account.id,
            funding_account_id=cash_account.id,
            amount_minor=10000,
            transaction_date=date(2026, 7, 1),
        ))
        session.commit()

        svc.delete_receivable_transaction(session, tx1.id)
        session.commit()

        recalc = balance_svc.recalculate_account(
            session, receivable_account.id
        )
        assert recalc == 0


class TestNonReceivableBlocked:
    """验证普通流水不能写入应收账户。"""

    def test_expense_to_receivable_blocked(
        self,
        migrated_db: Path,
        receivable_account: Account,
    ) -> None:
        """尝试将支出写入应收账户应被拒绝。"""
        from mym2.services.dto import CreateTransactionDTO

        session = get_session()
        ledger = LedgerService()

        with pytest.raises(ValueError, match='只能由应收专用服务写入'):
            ledger.create_transaction(session, CreateTransactionDTO(
                transaction_type=TransactionType.EXPENSE,
                transaction_date=date(2026, 7, 1),
                account_out_id=receivable_account.id,
                amount_minor=5000,
                category_id=None,
            ))

    def test_income_to_receivable_blocked(
        self,
        migrated_db: Path,
        receivable_account: Account,
    ) -> None:
        """尝试将收入写入应收账户应被拒绝。"""
        from mym2.services.dto import CreateTransactionDTO

        session = get_session()
        ledger = LedgerService()

        with pytest.raises(ValueError, match='只能由应收专用服务写入'):
            ledger.create_transaction(session, CreateTransactionDTO(
                transaction_type=TransactionType.INCOME,
                transaction_date=date(2026, 7, 1),
                account_out_id=receivable_account.id,
                account_in_id=receivable_account.id,
                amount_minor=5000,
                category_id=None,
            ))
