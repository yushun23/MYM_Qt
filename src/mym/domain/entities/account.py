"""Account entity – represents a financial account in the ledger."""

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import AccountType
from mym.infrastructure.database.base import (
    Base,
    IntegerPrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
)
from mym.infrastructure.database.types_ import Money


class Account(Base, IntegerPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Financial account: asset, liability, receivable, or investment_linked."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_account_name"),
        CheckConstraint("account_type IN ('asset','liability','receivable','investment_linked')",
                        name="ck_account_type"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(String(30), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name='{self.name}', type={self.account_type})>"
