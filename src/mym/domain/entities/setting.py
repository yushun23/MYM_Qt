"""AppSetting entity – ledger-scoped settings stored in database."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mym.infrastructure.database.base import Base, IntegerPrimaryKeyMixin, TimestampMixin


class AppSetting(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Key-value settings stored per ledger."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)

    def __repr__(self) -> str:
        return f"<AppSetting(key='{self.key}', value='{self.value}')>"
