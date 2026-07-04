"""LedgerService 集成测试。

覆盖：创建/编辑/删除流水、余额重算、验证规则、审计、事务回滚。
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest

from mym2.db.engine import create_mym2_engine
from mym2.db.migrate import set_alembic_ini_path, upgrade_to_head
from mym2.db.models import Account, AuditEvent, Category, Transaction
from mym2.db.session import (
    get_session,
    init_session_factory,
    remove_session,
    reset_session_factory,
)
from mym2.domain.enums import (
    AccountType,
    AuditAction,
    TransactionType,
)
from mym2.services.balance_service import BalanceService
from mym2.services.dto import CreateTransactionDTO, UpdateTransactionDTO
from mym2.services.ledger_service import LedgerService

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
    init_session_factory(engine)
    yield temp_db
    remove_session()
    reset_session_factory()
    engine.dispose()


@pytest.fixture
def service() -> LedgerService:
    return LedgerService()


@pytest.fixture
def balance_svc() -> BalanceService:
    return BalanceService()


@pytest.fixture
def cash_account(migrated_db: Path) -> Account:
    """创建一个现金账户。"""
    session = get_session()
    acct = Account(
        name='现金',
        type=AccountType.CASH,
        is_enabled=True,
        is_editable=True,
        is_locked=False,
        opening_balance_minor=0,
        current_balance_minor=0,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


@pytest.fixture
def bank_account(migrated_db: Path) -> Account:
    """创建一个银行账户。"""
    session = get_session()
    acct = Account(
        name='银行储蓄',
        type=AccountType.BANK,
        is_enabled=True,
        is_editable=True,
        is_locked=False,
        opening_balance_minor=500000,  # 5000 元
        current_balance_minor=500000,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


@pytest.fixture
def credit_card_account(migrated_db: Path) -> Account:
    """创建一个信用卡账户。"""
    session = get_session()
    acct = Account(
        name='招行信用卡',
        type=AccountType.CREDIT_CARD,
        is_enabled=True,
        is_editable=True,
        is_locked=False,
        opening_balance_minor=0,
        current_balance_minor=0,
        currency='CNY',
    )
    session.add(acct)
    session.commit()
    return acct


@pytest.fixture
def food_category(migrated_db: Path) -> Category:
    """创建餐饮分类。"""
    session = get_session()
    cat = Category(name='餐饮', type='expense', is_enabled=True)
    session.add(cat)
    session.commit()
    return cat


@pytest.fixture
def salary_category(migrated_db: Path) -> Category:
    """创建工资分类。"""
    session = get_session()
    cat = Category(name='工资', type='income', is_enabled=True)
    session.add(cat)
    session.commit()
    return cat


# ── 余额重算 ──────────────────────────────────────────


class TestBalanceRecalculation:
    """纯余额重算测试（不经过 LedgerService）。"""

    def test_balance_from_transactions(
        self,
        migrated_db: Path,
        balance_svc: BalanceService,
        bank_account: Account,
    ) -> None:
        """余额 = opening_balance + 流水 signed contributions。"""
        session = get_session()
        tx = Transaction(
            transaction_date=date(2026, 7, 1),
            type=TransactionType.EXPENSE,
            account_out_id=bank_account.id,
            amount_minor=10000,  # 100 元
            category_id=None,
            source='manual',
        )
        session.add(tx)
        session.commit()

        new_balance = balance_svc.recalculate_account(session, bank_account.id)
        # opening=500000, expense=10000 → 490000
        assert new_balance == 490000

    def test_balance_with_opening(
        self,
        migrated_db: Path,
        balance_svc: BalanceService,
        bank_account: Account,
    ) -> None:
        """有期初余额时，余额 = 期初 + 流水。"""
        session = get_session()
        tx1 = Transaction(
            transaction_date=date(2026, 7, 2),
            type=TransactionType.INCOME,
            account_out_id=bank_account.id,
            account_in_id=bank_account.id,
            amount_minor=30000,
            source='manual',
        )
        tx2 = Transaction(
            transaction_date=date(2026, 7, 3),
            type=TransactionType.EXPENSE,
            account_out_id=bank_account.id,
            amount_minor=15000,
            source='manual',
        )
        session.add_all([tx1, tx2])
        session.commit()

        new_balance = balance_svc.recalculate_account(session, bank_account.id)
        # 500000 + 30000 - 15000 = 515000
        assert new_balance == 515000


# ── 创建流水 ──────────────────────────────────────────


class TestCreateExpense:
    """资产支出测试。"""

    def test_expense_reduces_asset_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        food_category: Category,
    ) -> None:
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            amount_minor=5000,
            category_id=food_category.id,
            note='午餐',
        )
        tx = service.create_transaction(session, dto)
        session.commit()

        # 余额应减少
        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 495000  # 5000 - 50

        # 审计事件
        events = session.query(AuditEvent).filter_by(
            action=AuditAction.CREATE, entity_type='transaction', entity_id=tx.id
        ).all()
        assert len(events) == 1

    def test_expense_without_category_rejected(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
    ) -> None:
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            amount_minor=5000,
        )
        with pytest.raises(ValueError, match='必须指定分类'):
            service.create_transaction(session, dto)

    def test_expense_with_income_category_rejected(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        salary_category: Category,
    ) -> None:
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            amount_minor=5000,
            category_id=salary_category.id,  # 收入分类
        )
        with pytest.raises(ValueError, match='支出分类'):
            service.create_transaction(session, dto)


class TestCreateIncome:
    """资产收入测试。"""

    def test_income_increases_asset_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        salary_category: Category,
    ) -> None:
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.INCOME,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,  # 收入账户
            account_in_id=bank_account.id,
            amount_minor=200000,
            category_id=salary_category.id,
            note='7月工资',
        )
        service.create_transaction(session, dto)
        session.commit()

        # 余额增加
        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 700000  # 500000 + 200000


class TestCreateTransfer:
    """转账测试。"""

    def test_transfer_between_assets(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        cash_account: Account,
    ) -> None:
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.TRANSFER,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            account_in_id=cash_account.id,
            amount_minor=100000,
            note='取现',
        )
        service.create_transaction(session, dto)
        session.commit()

        # bank 余额减少
        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 400000  # 500000 - 100000

        # cash 余额增加
        session.refresh(cash_account)
        assert cash_account.current_balance_minor == 100000  # 0 + 100000

    def test_transfer_same_account_rejected(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
    ) -> None:
        """转账的两个账户不能相同。"""
        with pytest.raises(ValueError, match='不能相同'):
            CreateTransactionDTO(
                transaction_type=TransactionType.TRANSFER,
                transaction_date=date(2026, 7, 4),
                account_out_id=bank_account.id,
                account_in_id=bank_account.id,
                amount_minor=100000,
            )

    def test_transfer_with_category_rejected(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        cash_account: Account,
        food_category: Category,
    ) -> None:
        """转账不支持关联分类。"""
        with pytest.raises(ValueError, match='不支持关联分类'):
            CreateTransactionDTO(
                transaction_type=TransactionType.TRANSFER,
                transaction_date=date(2026, 7, 4),
                account_out_id=bank_account.id,
                account_in_id=cash_account.id,
                amount_minor=100000,
                category_id=food_category.id,
            )


class TestCreditCard:
    """信用卡（负债）账户测试。"""

    def test_credit_card_expense_increases_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        credit_card_account: Account,
        food_category: Category,
    ) -> None:
        """信用卡消费：余额增加（欠款增多）。"""
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=credit_card_account.id,
            amount_minor=5000,
            category_id=food_category.id,
            note='外卖',
        )
        service.create_transaction(session, dto)
        session.commit()

        session.refresh(credit_card_account)
        assert credit_card_account.current_balance_minor == 5000  # 欠款 50 元

    def test_credit_card_repayment_decreases_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        credit_card_account: Account,
        bank_account: Account,
    ) -> None:
        """信用卡还款（转入）：余额减少（欠款减少）。

        先产生一笔消费让信用卡有欠款，再从银行转账还款。
        """
        session = get_session()

        # 先消费
        tx_exp = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=credit_card_account.id,
            amount_minor=20000,
            category_id=None,
        )
        # 创建消费分类
        cat = Category(name='购物', type='expense', is_enabled=True)
        session.add(cat)
        session.flush()
        tx_exp.category_id = cat.id
        service.create_transaction(session, tx_exp)

        # 还款（从银行转入信用卡）
        tx_repay = CreateTransactionDTO(
            transaction_type=TransactionType.TRANSFER,
            transaction_date=date(2026, 7, 5),
            account_out_id=bank_account.id,
            account_in_id=credit_card_account.id,
            amount_minor=20000,
            note='还信用卡',
        )
        service.create_transaction(session, tx_repay)
        session.commit()

        # 信用卡余额应为 0（欠款已还清）
        session.refresh(credit_card_account)
        assert credit_card_account.current_balance_minor == 0

        # 银行余额应减少
        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 480000  # 500000 - 20000


# ── 编辑流水 ──────────────────────────────────────────


class TestUpdateTransaction:
    """编辑流水测试。"""

    def test_edit_expense_amount(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        food_category: Category,
    ) -> None:
        """编辑支出金额后余额正确重算。"""
        session = get_session()

        # 先创建
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 1),
            account_out_id=bank_account.id,
            amount_minor=5000,
            category_id=food_category.id,
        )
        tx = service.create_transaction(session, dto)
        session.commit()
        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 495000

        # 编辑金额
        update_dto = UpdateTransactionDTO(amount_minor=10000)
        service.update_transaction(session, tx.id, update_dto)
        session.commit()

        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 490000  # 500000 - 10000

        # 审计事件
        events = session.query(AuditEvent).filter_by(
            action=AuditAction.UPDATE, entity_type='transaction', entity_id=tx.id
        ).all()
        assert len(events) == 1

    def test_edit_note_preserves_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        food_category: Category,
    ) -> None:
        """仅编辑备注不影响余额。"""
        session = get_session()

        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 1),
            account_out_id=bank_account.id,
            amount_minor=5000,
            category_id=food_category.id,
        )
        tx = service.create_transaction(session, dto)
        session.commit()

        update_dto = UpdateTransactionDTO(note='修改后的备注')
        service.update_transaction(session, tx.id, update_dto)
        session.commit()

        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 495000


# ── 删除流水 ──────────────────────────────────────────


class TestDeleteTransaction:
    """删除流水测试。"""

    def test_delete_expense_restores_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        food_category: Category,
    ) -> None:
        """删除支出后余额恢复到期初。"""
        session = get_session()

        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 1),
            account_out_id=bank_account.id,
            amount_minor=5000,
            category_id=food_category.id,
        )
        tx = service.create_transaction(session, dto)
        session.commit()

        service.delete_transaction(session, tx.id)
        session.commit()

        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 500000  # 恢复

        # 审计事件
        events = session.query(AuditEvent).filter_by(
            action=AuditAction.DELETE, entity_type='transaction', entity_id=tx.id
        ).all()
        assert len(events) == 1


# ── 验证与拒绝 ────────────────────────────────────────


class TestValidation:
    """账户/分类/状态验证测试。"""

    def test_disabled_account_rejected(
        self,
        migrated_db: Path,
        service: LedgerService,
        food_category: Category,
    ) -> None:
        """停用账户不可写入。"""
        session = get_session()
        disabled = Account(
            name='停用账户',
            type=AccountType.CASH,
            is_enabled=False,
            is_editable=True,
        )
        session.add(disabled)
        session.commit()

        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=disabled.id,
            amount_minor=1000,
            category_id=food_category.id,
        )
        with pytest.raises(ValueError, match='停用'):
            service.create_transaction(session, dto)

    def test_locked_historical_settlement_immutable(
        self,
        migrated_db: Path,
        service: LedgerService,
    ) -> None:
        """历史结算流水不可编辑/删除。"""
        session = get_session()
        acct = Account(
            name='投资快照',
            type=AccountType.INVESTMENT_SNAPSHOT,
            is_enabled=True,
            is_editable=False,
            is_locked=True,
            opening_balance_minor=100000,
            current_balance_minor=100000,
        )
        session.add(acct)
        session.flush()

        tx = Transaction(
            transaction_date=date(2026, 1, 1),
            type=TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT,
            account_out_id=acct.id,
            amount_minor=100000,
            is_locked=True,
            source='migration',
        )
        session.add(tx)
        session.commit()

        with pytest.raises(ValueError, match='不可编辑'):
            service.update_transaction(session, tx.id, UpdateTransactionDTO(note='x'))

        with pytest.raises(ValueError, match='不可编辑'):
            service.delete_transaction(session, tx.id)

    def test_locked_historical_account_readonly(
        self,
        migrated_db: Path,
        service: LedgerService,
        food_category: Category,
    ) -> None:
        """锁定/不可编辑账户拒绝写入。"""
        session = get_session()
        locked = Account(
            name='历史快照账户',
            type=AccountType.INVESTMENT_SNAPSHOT,
            is_enabled=True,
            is_editable=False,
            is_locked=True,
        )
        session.add(locked)
        session.commit()

        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=locked.id,
            amount_minor=1000,
            category_id=food_category.id,
        )
        with pytest.raises(ValueError, match='不可编辑'):
            service.create_transaction(session, dto)

    def test_receivable_write_blocked_via_ledger(
        self,
        migrated_db: Path,
        service: LedgerService,
        salary_category: Category,
    ) -> None:
        """应收账户不能通过 LedgerService 直写。"""
        session = get_session()
        receivable = Account(
            name='张三借款',
            type=AccountType.RECEIVABLE,
            is_enabled=True,
            is_editable=True,
        )
        session.add(receivable)
        session.commit()

        # 尝试以 income 写入 receivable
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.INCOME,
            transaction_date=date(2026, 7, 4),
            account_out_id=receivable.id,
            account_in_id=receivable.id,
            amount_minor=10000,
            category_id=salary_category.id,
        )
        with pytest.raises(ValueError, match='应收'):
            service.create_transaction(session, dto)

    def test_category_compatibility_expense(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
        salary_category: Category,
    ) -> None:
        """支出不能关联收入分类。"""
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            amount_minor=5000,
            category_id=salary_category.id,
        )
        with pytest.raises(ValueError, match='支出分类'):
            service.create_transaction(session, dto)

    def test_missing_account_in_for_transfer(
        self,
        migrated_db: Path,
        bank_account: Account,
    ) -> None:
        """转账必须提供 account_in_id。"""
        with pytest.raises(ValueError, match='account_in_id'):
            CreateTransactionDTO(
                transaction_type=TransactionType.TRANSFER,
                transaction_date=date(2026, 7, 4),
                account_out_id=bank_account.id,
                amount_minor=100000,
            )


# ── 异常事务回滚 ──────────────────────────────────────


class TestTransactionRollback:
    """事务回滚测试。"""

    def test_failed_create_does_not_persist(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
    ) -> None:
        """创建失败不留下数据。"""
        session = get_session()
        initial_count = session.query(Transaction).count()

        try:
            dto = CreateTransactionDTO(
                transaction_type=TransactionType.EXPENSE,
                transaction_date=date(2026, 7, 4),
                account_out_id=bank_account.id,
                amount_minor=5000,
                # 故意不加 category_id
            )
            service.create_transaction(session, dto)
            session.commit()
        except ValueError:
            session.rollback()

        final_count = session.query(Transaction).count()
        assert final_count == initial_count

    def test_delete_nonexistent_transaction(
        self,
        migrated_db: Path,
        service: LedgerService,
    ) -> None:
        """删除不存在的流水抛异常。"""
        session = get_session()
        with pytest.raises(ValueError, match='不存在'):
            service.delete_transaction(session, 'nonexistent_id')


# ── 余额可重算性 ──────────────────────────────────────


class TestBalanceRecomputable:
    """验证余额始终 = opening_balance + 流水重算。"""

    def test_balance_after_multiple_ops(
        self,
        migrated_db: Path,
        service: LedgerService,
        balance_svc: BalanceService,
        bank_account: Account,
        cash_account: Account,
        food_category: Category,
        salary_category: Category,
    ) -> None:
        """多次操作后余额与逐笔重算一致。"""
        session = get_session()

        # 收入
        service.create_transaction(session, CreateTransactionDTO(
            transaction_type=TransactionType.INCOME,
            transaction_date=date(2026, 7, 1),
            account_out_id=bank_account.id,
            account_in_id=bank_account.id,
            amount_minor=200000,
            category_id=salary_category.id,
        ))

        # 支出 x2
        service.create_transaction(session, CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 2),
            account_out_id=bank_account.id,
            amount_minor=15000,
            category_id=food_category.id,
        ))
        service.create_transaction(session, CreateTransactionDTO(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 3),
            account_out_id=bank_account.id,
            amount_minor=35000,
            category_id=food_category.id,
        ))

        # 转账
        service.create_transaction(session, CreateTransactionDTO(
            transaction_type=TransactionType.TRANSFER,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            account_in_id=cash_account.id,
            amount_minor=50000,
        ))

        session.commit()

        # 重算
        recalc_bank = balance_svc.recalculate_account(session, bank_account.id)
        recalc_cash = balance_svc.recalculate_account(session, cash_account.id)

        # 预期: 500000 + 200000 - 15000 - 35000 - 50000 = 600000
        assert recalc_bank == 600000
        # 预期: 0 + 50000 = 50000
        assert recalc_cash == 50000

        # 与 current_balance_minor 一致
        session.refresh(bank_account)
        session.refresh(cash_account)
        assert bank_account.current_balance_minor == recalc_bank
        assert cash_account.current_balance_minor == recalc_cash


# ── balance_adjustment ────────────────────────────────


class TestBalanceAdjustment:
    """余额调节测试。"""

    def test_balance_adjustment_adds_to_balance(
        self,
        migrated_db: Path,
        service: LedgerService,
        bank_account: Account,
    ) -> None:
        session = get_session()
        dto = CreateTransactionDTO(
            transaction_type=TransactionType.BALANCE_ADJUSTMENT,
            transaction_date=date(2026, 7, 4),
            account_out_id=bank_account.id,
            amount_minor=10000,
            note='调节余额',
        )
        service.create_transaction(session, dto)
        session.commit()

        session.refresh(bank_account)
        assert bank_account.current_balance_minor == 510000  # 500000 + 10000
