"""Transaction and TransactionLine entities – core accounting records."""

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import (
    TransactionRole,
    TransactionSource,
    TransactionStatus,
)
from mym.infrastructure.database.base import (
    Base,
    IntegerPrimaryKeyMixin,
    TimestampMixin,
)
from mym.infrastructure.database.types_ import Money


class Transaction(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Transaction header – represents one accounting entry (单据头)."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("status IN ('draft','posted','void')", name="ck_tx_status"),
        CheckConstraint("source IN ('manual','import','migration','ai','system')",
                        name="ck_tx_source"),
    )

    # Business type: income, expense, transfer, lend, recover, balance_adjustment,
    # stock_profit, stock_loss
    business_type: Mapped[str] = mapped_column(String(30), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[TransactionSource] = mapped_column(String(20), default=TransactionSource.MANUAL, nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(String(20), default=TransactionStatus.POSTED, nullable=False)
    import_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("import_jobs.id"), nullable=True)
    settlement_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("investment_settlements.id"), nullable=True)
    is_cleared: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Relationships
    lines: Mapped[list["TransactionLine"]] = relationship(
        "TransactionLine", back_populates="transaction",
        cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction(id={self.id}, type='{self.business_type}', "
            f"date={self.transaction_date}, status={self.status})>"
        )


class TransactionLine(Base, IntegerPrimaryKeyMixin):
    """Transaction line item – represents one leg of a transaction (明细行)."""

    __tablename__ = "transaction_lines"
    __table_args__ = (
        CheckConstraint("role IN ('debit','credit')", name="ck_line_role"),
    )

    transaction_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    role: Mapped[TransactionRole] = mapped_column(String(10), nullable=False)
    signed_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)

    # Relationships
    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="lines")
    account: Mapped["Account"] = relationship("Account", lazy="selectin")
    category: Mapped["Category | None"] = relationship("Category", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<TransactionLine(id={self.id}, role={self.role}, "
            f"amount={self.signed_amount})>"
        )


# Ensure forward references work
from mym.domain.entities.account import Account  # noqa: E402, F811
from mym.domain.entities.category import Category  # noqa: E402, F811
