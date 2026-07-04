"""预算模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym2.db.base import Base, TimestampMixin, UUIDMixin
from mym2.db.models.category import Category


class BudgetPeriod(Base, UUIDMixin):
    """预算期间（年-月）。"""

    __tablename__ = 'budget_periods'
    __table_args__ = (
        UniqueConstraint('year', 'month', name='uq_budget_period_ym'),
    )

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    lines: Mapped[list[BudgetLine]] = relationship(
        'BudgetLine', back_populates='period', cascade='all, delete-orphan'
    )


class BudgetLine(Base, UUIDMixin, TimestampMixin):
    """预算明细行。"""

    __tablename__ = 'budget_lines'

    budget_period_id: Mapped[str] = mapped_column(
        String(32), ForeignKey('budget_periods.id'), nullable=False
    )
    category_id: Mapped[str] = mapped_column(
        String(32), ForeignKey('categories.id'), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default='expense', comment='expense/income'
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, comment='预算金额（分）')
    threshold_minor: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment='阈值金额（分）'
    )
    group: Mapped[str | None] = mapped_column(
        'group', String(50), nullable=True, quote=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))

    period: Mapped[BudgetPeriod] = relationship('BudgetPeriod', back_populates='lines')
    category: Mapped[Category] = relationship('Category')
