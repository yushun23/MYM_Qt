"""分类模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym2.db.base import Base, TimestampMixin, UUIDMixin


class Category(Base, UUIDMixin, TimestampMixin):
    """收支分类。

    支持类型：expense, income, system。
    支持树形结构（parent_id 自引用）。
    """

    __tablename__ = 'categories'

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default='expense')
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey('categories.id'), nullable=True
    )
    color: Mapped[str | None] = mapped_column(String(20))
    icon: Mapped[str | None] = mapped_column(String(50))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parent: Mapped[Category | None] = relationship(
        'Category', remote_side='Category.id', back_populates='children'
    )
    children: Mapped[list[Category]] = relationship(
        'Category', back_populates='parent'
    )
