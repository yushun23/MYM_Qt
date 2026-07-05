"""DTOs for transaction operations."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass
class TransactionLineDTO:
    """DTO for a transaction line."""

    account_id: int
    role: str  # "debit" | "credit"
    signed_amount: Decimal
    category_id: Optional[int] = None
    memo: Optional[str] = None
    sort_order: int = 0


@dataclass
class CreateTransactionDTO:
    """DTO for creating a transaction."""

    business_type: str
    transaction_date: date
    source: str = "manual"
    description: Optional[str] = None
    lines: list[TransactionLineDTO] = field(default_factory=list)


@dataclass
class UpdateTransactionDTO:
    """DTO for updating a transaction."""

    transaction_id: int
    transaction_date: Optional[date] = None
    description: Optional[str] = None
    lines: Optional[list[TransactionLineDTO]] = None
