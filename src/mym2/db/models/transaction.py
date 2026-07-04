"""流水/交易模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym2.db.base import Base, TimestampMixin, UUIDMixin
from mym2.db.models.account import Account
from mym2.db.models.category import Category


class Transaction(Base, UUIDMixin, TimestampMixin):
    """流水记录。

    类型：expense, income, transfer, receivable_advance,
          receivable_repayment, balance_adjustment,
          historical_investment_settlement。
    """

    __tablename__ = 'transactions'
    __table_args__ = (
        Index('ix_trans_date_id', 'transaction_date', 'id'),
        Index('ix_trans_out_date', 'account_out_id', 'transaction_date'),
        Index('ix_trans_in_date', 'account_in_id', 'transaction_date'),
        Index('ix_trans_cat_date', 'category_id', 'transaction_date'),
        Index('ix_trans_type_date', 'type', 'transaction_date'),
    )

    transaction_date: Mapped[str] = mapped_column(
        Date, nullable=False, comment='交易日期'
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    category_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey('categories.id'), nullable=True
    )
    account_out_id: Mapped[str] = mapped_column(
        String(32), ForeignKey('accounts.id'), nullable=False
    )
    account_in_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey('accounts.id'), nullable=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, comment='金额（分）')
    note: Mapped[str | None] = mapped_column(String(1000))
    is_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str | None] = mapped_column(String(30), comment='manual/import/ai')
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    category: Mapped[Category | None] = relationship('Category')
    account_out: Mapped[Account] = relationship(
        'Account', foreign_keys=[account_out_id]
    )
    account_in: Mapped[Account | None] = relationship(
        'Account', foreign_keys=[account_in_id]
    )
