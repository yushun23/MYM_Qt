"""应用设置模型（仅非秘密设置）。"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from mym2.db.base import Base, UUIDMixin


class AppSetting(Base, UUIDMixin):
    """应用设置 — 只能存储非秘密配置。

    禁止存储：API key、密码、token、password_hash。
    """

    __tablename__ = 'app_settings'

    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(String(2000), nullable=False)
