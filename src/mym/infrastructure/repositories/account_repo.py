"""Account repository."""

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mym.domain.entities.account import Account
from mym.domain.enums import AccountType


class AccountRepository:
    """Repository for Account entity."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, account_id: int) -> Account | None:
        return self._session.get(Account, account_id)

    def get_all(self, *, include_deleted: bool = False) -> list[Account]:
        stmt = select(Account)
        if not include_deleted:
            stmt = stmt.where(Account.is_deleted == False)  # noqa: E712
        return list(self._session.execute(stmt).scalars().all())

    def get_enabled_normal(self) -> list[Account]:
        """Get non-system-locked, non-archived accounts for normal use."""
        stmt = select(Account).where(
            Account.is_deleted == False,  # noqa: E712
            Account.is_enabled == True,  # noqa: E712
            Account.is_archived == False,  # noqa: E712
            Account.is_system_locked == False,  # noqa: E712
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_by_type(self, account_type: AccountType) -> list[Account]:
        """List accounts of a specific type."""
        stmt = select(Account).where(
            Account.is_deleted == False,  # noqa: E712
            Account.account_type == account_type,
            Account.is_archived == False,  # noqa: E712
        )
        return list(self._session.execute(stmt).scalars().all())

    def add(self, account: Account) -> None:
        self._session.add(account)

    def update_balance(self, account_id: int, delta: Decimal) -> None:
        """Atomically increment current_balance by delta."""
        self._session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(current_balance=Account.current_balance + delta)
        )

    def set_balance(self, account_id: int, delta: Decimal) -> None:
        """Set current_balance to a specific value."""
        self._session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(current_balance=delta)
        )
