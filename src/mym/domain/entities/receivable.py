"""ReceivableCase and ReceivableEvent entities – accounts receivable domain."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import ReceivableStatus
from mym.infrastructure.database.base import (
    Base,
    IntegerPrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
)
from mym.infrastructure.database.types_ import Money


class ReceivableCase(Base, IntegerPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A receivable case – represents money owed (垫付/借出)."""

    __tablename__ = "receivable_cases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','partially_recovered','fully_recovered','written_off')",
            name="ck_rec_status",
        ),
    )

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False
    )
    debtor: Mapped[str] = mapped_column(String(200), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    recovered_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    written_off_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    status: Mapped[ReceivableStatus] = mapped_column(
        String(30), default=ReceivableStatus.PENDING, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    import_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_jobs.id"), nullable=True
    )

    # Relationships
    account: Mapped["Account"] = relationship("Account", lazy="selectin")
    events: Mapped[list["ReceivableEvent"]] = relationship(
        "ReceivableEvent", back_populates="case",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="ReceivableEvent.event_date",
    )

    @property
    def outstanding_amount(self) -> Decimal:
        """Amount still outstanding."""
        return self.total_amount - self.recovered_amount - self.written_off_amount

    def __repr__(self) -> str:
        return (
            f"<ReceivableCase(id={self.id}, debtor='{self.debtor}', "
            f"total={self.total_amount}, recovered={self.recovered_amount}, "
            f"status={self.status})>"
        )


class ReceivableEvent(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """An event in a receivable case lifecycle: advance, recovery, write-off."""

    __tablename__ = "receivable_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('advance','partial_recovery','full_recovery','write_off')",
            name="ck_rec_event_type",
        ),
    )

    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("receivable_cases.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    transaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    case: Mapped["ReceivableCase"] = relationship("ReceivableCase", back_populates="events")

    def __repr__(self) -> str:
        return (
            f"<ReceivableEvent(id={self.id}, case_id={self.case_id}, "
            f"type='{self.event_type}', amount={self.amount})>"
        )


# Ensure forward references
from mym.domain.entities.account import Account  # noqa: E402, F811
