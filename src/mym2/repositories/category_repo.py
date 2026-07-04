"""分类仓储 — 只读查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym2.db.models.category import Category


class CategoryRepository:
    """分类数据访问。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, category_id: str) -> Category | None:
        """按主键获取分类。"""
        return self._session.get(Category, category_id)

    def get_all(self) -> list[Category]:
        """获取所有分类。"""
        return list(
            self._session.scalars(select(Category).order_by(Category.sort_order, Category.name))
        )
