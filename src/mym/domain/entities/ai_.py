"""AI domain entities – chat sessions, messages, and action specifications."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import ActionRiskLevel
from mym.infrastructure.database.base import Base, IntegerPrimaryKeyMixin, TimestampMixin


class ChatSession(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """An AI chat session – isolated per ledger."""

    __tablename__ = "chat_sessions"

    title: Mapped[str] = mapped_column(String(200), default="新对话", nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="session",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, title='{self.title}')>"


class ChatMessage(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """A single message in an AI chat session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system','tool')",
            name="ck_chat_role",
        ),
    )

    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    has_action_proposal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    action_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # pending, approved, rejected, executed

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<ChatMessage(id={self.id}, role='{self.role}', "
            f"session={self.session_id})>"
        )
