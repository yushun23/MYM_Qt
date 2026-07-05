"""Category repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym.domain.entities.category import Category


class CategoryRepository:
    """Repository for Category entity."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, category_id: int) -> Category | None:
        return self._session.get(Category, category_id)

    def get_all(self, *, include_deleted: bool = False) -> list[Category]:
        stmt = select(Category)
        if not include_deleted:
            stmt = stmt.where(Category.is_deleted == False)  # noqa: E712
        return list(self._session.execute(stmt).scalars().all())

    def add(self, category: Category) -> None:
        self._session.add(category)
