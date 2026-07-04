"""账户模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mym2.db.base import Base, TimestampMixin, UUIDMixin


class Account(Base, UUIDMixin, TimestampMixin):
    """账户。

    支持类型：cash, bank, credit_card, investment_snapshot, receivable。
    """

    __tablename__ = 'accounts'

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False, default='cash')
    group: Mapped[str | None] = mapped_column(String(50))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    opening_balance_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_balance_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default='CNY', nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
