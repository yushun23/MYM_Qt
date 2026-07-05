"""Fixed ledger scenarios for regression testing."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.enums import AccountType, CategoryType


def _make_account(session: Session, name: str, acct_type: AccountType,
                  opening: str = "0") -> Account:
    dec = Decimal(opening)
    a = Account(name=name, account_type=acct_type, opening_balance=dec, current_balance=dec)
    session.add(a)
    session.flush()
    return a


def _make_category(session: Session, name: str, cat_type: CategoryType) -> Category:
    c = Category(name=name, category_type=cat_type)
    session.add(c)
    session.flush()
    return c


def _post_tx(session: Session, dto: CreateTransactionDTO) -> int:
    result = CreateTransactionUseCase(session).execute(dto)
    if not result.success:
        raise RuntimeError(f"Failed to create transaction: {result.errors}")
    return result.transaction_id


def scenario_empty(session: Session) -> dict:
    """Empty ledger with just one base account."""
    bank = _make_account(session, "Cash", AccountType.ASSET, "0")
    return {"accounts": [bank]}


def scenario_salary_and_dining(session: Session) -> dict:
    """Monthly salary income + dining expense."""
    bank = _make_account(session, "PayrollCard", AccountType.ASSET, "10000")
    income_cat = _make_category(session, "Salary", CategoryType.INCOME)
    expense_cat = _make_category(session, "Dining", CategoryType.EXPENSE)

    _post_tx(session, CreateTransactionDTO(
        business_type="income",
        transaction_date=date(2026, 7, 1),
        description="July salary",
        lines=[
            TransactionLineDTO(account_id=bank.id, role="debit",
                               signed_amount=Decimal("5000"), category_id=income_cat.id),
            TransactionLineDTO(account_id=bank.id, role="credit",
                               signed_amount=Decimal("5000"), category_id=income_cat.id),
        ],
    ))

    _post_tx(session, CreateTransactionDTO(
        business_type="expense",
        transaction_date=date(2026, 7, 2),
        description="Lunch",
        lines=[
            TransactionLineDTO(account_id=bank.id, role="debit",
                               signed_amount=Decimal("200"), category_id=expense_cat.id),
            TransactionLineDTO(account_id=bank.id, role="credit",
                               signed_amount=Decimal("200"), category_id=expense_cat.id),
        ],
    ))

    return {
        "bank": bank,
        "expected_bank_balance": Decimal("10000"),
    }


def scenario_multi_account_transfer(session: Session) -> dict:
    """Transfer between two asset accounts."""
    bank_a = _make_account(session, "DebitCard", AccountType.ASSET, "10000")
    bank_b = _make_account(session, "Alipay", AccountType.ASSET, "2000")

    _post_tx(session, CreateTransactionDTO(
        business_type="transfer",
        transaction_date=date(2026, 7, 3),
        description="Transfer to Alipay",
        lines=[
            TransactionLineDTO(account_id=bank_b.id, role="debit",
                               signed_amount=Decimal("3000")),
            TransactionLineDTO(account_id=bank_a.id, role="credit",
                               signed_amount=Decimal("3000")),
        ],
    ))

    return {
        "bank_a": bank_a,
        "bank_b": bank_b,
        "expected_a_balance": Decimal("7000"),
        "expected_b_balance": Decimal("5000"),
    }


def scenario_credit_card_repayment(session: Session) -> dict:
    """Credit card consumption and repayment."""
    bank = _make_account(session, "DebitCard", AccountType.ASSET, "5000")
    card = _make_account(session, "CreditCard", AccountType.LIABILITY, "0")
    cat = _make_category(session, "Shopping", CategoryType.EXPENSE)

    _post_tx(session, CreateTransactionDTO(
        business_type="expense",
        transaction_date=date(2026, 7, 5),
        description="Shopping",
        lines=[
            TransactionLineDTO(account_id=card.id, role="debit",
                               signed_amount=Decimal("500"), category_id=cat.id),
            TransactionLineDTO(account_id=card.id, role="credit",
                               signed_amount=Decimal("500"), category_id=cat.id),
        ],
    ))

    _post_tx(session, CreateTransactionDTO(
        business_type="transfer",
        transaction_date=date(2026, 7, 20),
        description="Pay credit card",
        lines=[
            TransactionLineDTO(account_id=card.id, role="debit",
                               signed_amount=Decimal("500")),
            TransactionLineDTO(account_id=bank.id, role="credit",
                               signed_amount=Decimal("500")),
        ],
    ))

    return {
        "bank": bank,
        "card": card,
        "expected_bank_balance": Decimal("4500"),
        "expected_card_balance": Decimal("-500"),
    }
