"""P5 tests: Core accounting service – create, update, void, rebuild balances."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.application.use_cases.rebuild_balances import RebuildAccountBalancesUseCase
from mym.application.use_cases.update_transaction import (
    UpdateTransactionDTO,
    UpdateTransactionUseCase,
    VoidTransactionUseCase,
)
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


def _create_account(session: Session, name: str, acct_type: AccountType,
                    opening_balance: Decimal = Decimal("0")) -> Account:
    account = Account(name=name, account_type=acct_type, opening_balance=opening_balance,
                      current_balance=opening_balance)
    session.add(account)
    session.flush()
    return account


def _create_category(session: Session, name: str, cat_type: CategoryType) -> Category:
    cat = Category(name=name, category_type=cat_type)
    session.add(cat)
    session.flush()
    return cat


class TestCreateTransaction:
    """Tests for creating income, expense, and transfer transactions."""

    def test_create_transfer(self, session: Session) -> None:
        bank_a = _create_account(session, "银行卡A", AccountType.ASSET, Decimal("5000"))
        bank_b = _create_account(session, "银行卡B", AccountType.ASSET, Decimal("1000"))

        # Transfer: bank_b debit +1000, bank_a credit +1000
        dto = CreateTransactionDTO(
            business_type="transfer",
            transaction_date=date(2026, 7, 3),
            description="转账",
            lines=[
                TransactionLineDTO(account_id=bank_b.id, role="debit",
                                   signed_amount=Decimal("1000")),
                TransactionLineDTO(account_id=bank_a.id, role="credit",
                                   signed_amount=Decimal("1000")),
            ],
        )

        uc = CreateTransactionUseCase(session)
        result = uc.execute(dto)
        assert result.success, result.errors

        session.refresh(bank_a)
        session.refresh(bank_b)
        # bank_b: debit +1000 on asset = +1000 → 2000
        assert bank_b.current_balance == Decimal("2000")
        # bank_a: credit +1000 on asset = -1000 → 4000
        assert bank_a.current_balance == Decimal("4000")

    def test_negative_amount_rejected(self, session: Session) -> None:
        bank = _create_account(session, "银行卡", AccountType.ASSET)
        dto = CreateTransactionDTO(
            business_type="expense",
            transaction_date=date(2026, 7, 1),
            lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("-50")),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("50")),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert not result.success

    def test_amount_not_conserved_rejected(self, session: Session) -> None:
        bank = _create_account(session, "银行卡", AccountType.ASSET)
        dto = CreateTransactionDTO(
            business_type="expense",
            transaction_date=date(2026, 7, 1),
            lines=[
                TransactionLineDTO(account_id=bank.id, role="debit", signed_amount=Decimal("100")),
                TransactionLineDTO(account_id=bank.id, role="credit", signed_amount=Decimal("50")),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert not result.success

    def test_liability_account_balance_direction(self, session: Session) -> None:
        """Liability: debit decreases, credit increases."""
        card = _create_account(session, "信用卡", AccountType.LIABILITY, Decimal("0"))

        # Use credit card: liability increases. debit=expense, credit=liability increase
        cat = _create_category(session, "购物", CategoryType.EXPENSE)
        dto = CreateTransactionDTO(
            business_type="expense",
            transaction_date=date(2026, 7, 5),
            lines=[
                TransactionLineDTO(account_id=card.id, role="debit",
                                   signed_amount=Decimal("200"), category_id=cat.id),
                TransactionLineDTO(account_id=card.id, role="credit",
                                   signed_amount=Decimal("200"), category_id=cat.id),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert result.success, result.errors

        session.refresh(card)
        # debit -200 (decrease liability) + credit +200 (increase liability) = net 0
        assert card.current_balance == Decimal("0")

        # More realistic: one asset account and one liability account
        bank = _create_account(session, "还款卡", AccountType.ASSET, Decimal("3000"))
        dto2 = CreateTransactionDTO(
            business_type="transfer",
            transaction_date=date(2026, 7, 10),
            description="还信用卡",
            lines=[
                TransactionLineDTO(account_id=card.id, role="debit",
                                   signed_amount=Decimal("500")),
                TransactionLineDTO(account_id=bank.id, role="credit",
                                   signed_amount=Decimal("500")),
            ],
        )
        result2 = CreateTransactionUseCase(session).execute(dto2)
        assert result2.success, result2.errors

        session.refresh(card)
        session.refresh(bank)
        # card: debit -500 (liability debit = decrease)
        # bank: credit -500 (asset credit = decrease)
        assert card.current_balance == Decimal("-500")
        assert bank.current_balance == Decimal("2500")


class TestUpdateTransaction:
    def test_update_tx_date(self, session: Session) -> None:
        bank_a = _create_account(session, "银行卡A", AccountType.ASSET, Decimal("5000"))
        bank_b = _create_account(session, "银行卡B", AccountType.ASSET, Decimal("1000"))

        dto = CreateTransactionDTO(
            business_type="transfer",
            transaction_date=date(2026, 7, 1),
            lines=[
                TransactionLineDTO(account_id=bank_b.id, role="debit", signed_amount=Decimal("500")),
                TransactionLineDTO(account_id=bank_a.id, role="credit", signed_amount=Decimal("500")),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert result.success
        tx_id = result.transaction_id

        update_dto = UpdateTransactionDTO(transaction_id=tx_id, transaction_date=date(2026, 7, 15))
        update_result = UpdateTransactionUseCase(session).execute(update_dto)
        assert update_result.success

        from mym.infrastructure.repositories.transaction_repo import TransactionRepository
        tx = TransactionRepository(session).get_by_id(tx_id)
        assert tx.transaction_date == date(2026, 7, 15)


class TestVoidTransaction:
    def test_void_reverses_balance(self, session: Session) -> None:
        bank_a = _create_account(session, "银行卡A", AccountType.ASSET, Decimal("5000"))
        bank_b = _create_account(session, "银行卡B", AccountType.ASSET, Decimal("1000"))

        dto = CreateTransactionDTO(
            business_type="transfer",
            transaction_date=date(2026, 7, 3),
            lines=[
                TransactionLineDTO(account_id=bank_b.id, role="debit", signed_amount=Decimal("1000")),
                TransactionLineDTO(account_id=bank_a.id, role="credit", signed_amount=Decimal("1000")),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert result.success

        void_result = VoidTransactionUseCase(session).execute(result.transaction_id)
        assert void_result.success

        session.refresh(bank_a)
        session.refresh(bank_b)
        assert bank_a.current_balance == Decimal("5000")
        assert bank_b.current_balance == Decimal("1000")

    def test_void_nonexistent_fails(self, session: Session) -> None:
        result = VoidTransactionUseCase(session).execute(99999)
        assert not result.success


class TestRebuildBalances:
    def test_rebuild_fixes_balance(self, session: Session) -> None:
        bank_a = _create_account(session, "银行卡A", AccountType.ASSET, Decimal("5000"))
        bank_b = _create_account(session, "银行卡B", AccountType.ASSET, Decimal("1000"))

        dto = CreateTransactionDTO(
            business_type="transfer",
            transaction_date=date(2026, 7, 2),
            lines=[
                TransactionLineDTO(account_id=bank_b.id, role="debit", signed_amount=Decimal("300")),
                TransactionLineDTO(account_id=bank_a.id, role="credit", signed_amount=Decimal("300")),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert result.success

        # Corrupt balance
        bank_a.current_balance = Decimal("99999")
        session.flush()

        rebuild_uc = RebuildAccountBalancesUseCase(session)
        rebuild_result = rebuild_uc.execute()
        assert rebuild_result.success
        assert rebuild_result.accounts_checked > 0
        assert rebuild_result.accounts_fixed >= 1

        session.refresh(bank_a)
        assert bank_a.current_balance == Decimal("4700")  # 5000 - 300


class TestProtectedAccounts:
    def test_receivable_account_blocked(self, session: Session) -> None:
        recv = _create_account(session, "应收账款", AccountType.RECEIVABLE, Decimal("0"))
        cat = _create_category(session, "杂项", CategoryType.INCOME)
        dto = CreateTransactionDTO(
            business_type="income",
            transaction_date=date(2026, 7, 1),
            lines=[
                TransactionLineDTO(account_id=recv.id, role="debit", signed_amount=Decimal("100"), category_id=cat.id),
                TransactionLineDTO(account_id=recv.id, role="credit", signed_amount=Decimal("100"), category_id=cat.id),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert not result.success

    def test_investment_account_blocked(self, session: Session) -> None:
        inv = _create_account(session, "股票资金池", AccountType.INVESTMENT_LINKED, Decimal("0"))
        cat = _create_category(session, "杂项", CategoryType.EXPENSE)
        dto = CreateTransactionDTO(
            business_type="expense",
            transaction_date=date(2026, 7, 1),
            lines=[
                TransactionLineDTO(account_id=inv.id, role="debit", signed_amount=Decimal("100"), category_id=cat.id),
                TransactionLineDTO(account_id=inv.id, role="credit", signed_amount=Decimal("100"), category_id=cat.id),
            ],
        )
        result = CreateTransactionUseCase(session).execute(dto)
        assert not result.success
