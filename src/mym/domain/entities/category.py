"""Category entity – income, expense, or system category."""

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mym.domain.enums import CategoryType
from mym.infrastructure.database.base import (
    Base,
    IntegerPrimaryKeyMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class Category(Base, IntegerPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Category for classifying transactions (income, expense, system)."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("name", "category_type", name="uq_category_name_type"),
        CheckConstraint("category_type IN ('income','expense','system')",
                        name="ck_category_type"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category_type: Mapped[CategoryType] = mapped_column(String(20), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    include_in_reports: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}', type={self.category_type})>"
