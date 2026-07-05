"""BudgetPeriod and BudgetLine entities – monthly budget domain."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import BudgetStatus
from mym.infrastructure.database.base import Base, IntegerPrimaryKeyMixin, TimestampMixin
from mym.infrastructure.database.types_ import Money


class BudgetPeriod(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """A budget period – typically a calendar month."""

    __tablename__ = "budget_periods"
    __table_args__ = (
        UniqueConstraint("year", "month", name="uq_budget_year_month"),
        CheckConstraint("status IN ('open','closed')", name="ck_budget_status"),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_budget_month"),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[BudgetStatus] = mapped_column(
        String(20), default=BudgetStatus.OPEN, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lines: Mapped[list["BudgetLine"]] = relationship(
        "BudgetLine", back_populates="period",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="BudgetLine.sort_order",
    )

    @property
    def period_label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    @property
    def is_closed(self) -> bool:
        return self.status == BudgetStatus.CLOSED

    def __repr__(self) -> str:
        return (
            f"<BudgetPeriod(id={self.id}, period={self.period_label}, "
            f"status={self.status})>"
        )


class BudgetLine(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """A single budget line item – can be a group container or leaf item."""

    __tablename__ = "budget_lines"
    __table_args__ = (
        CheckConstraint(
            "budget_type IN ('income','expense')",
            name="ck_budget_line_type",
        ),
    )

    period_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_periods.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("budget_lines.id"), nullable=True
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    budget_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warn_threshold_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    period: Mapped["BudgetPeriod"] = relationship("BudgetPeriod", back_populates="lines")
    parent: Mapped["BudgetLine | None"] = relationship(
        "BudgetLine", remote_side="BudgetLine.id", backref="children"
    )
    category: Mapped["Category | None"] = relationship("Category", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<BudgetLine(id={self.id}, name='{self.name}', "
            f"planned={self.planned_amount}, type={self.budget_type})>"
        )


# Forward references
from mym.domain.entities.category import Category  # noqa: E402, F811
