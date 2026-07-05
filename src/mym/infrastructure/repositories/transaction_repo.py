"""Transaction repository."""

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import TransactionStatus


class TransactionRepository:
    """Repository for Transaction and TransactionLine entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, tx_id: int) -> Transaction | None:
        return self._session.get(Transaction, tx_id)

    def add(self, transaction: Transaction) -> None:
        self._session.add(transaction)

    def void(self, tx_id: int) -> None:
        """Mark a transaction as void."""
        self._session.execute(
            update(Transaction)
            .where(Transaction.id == tx_id)
            .values(status=TransactionStatus.VOID)
        )

    def get_lines_by_account(self, account_id: int) -> list[TransactionLine]:
        """Get all posted lines for an account."""
        stmt = (
            select(TransactionLine)
            .join(Transaction)
            .where(
                TransactionLine.account_id == account_id,
                Transaction.status == TransactionStatus.POSTED,
            )
        )
        return list(self._session.execute(stmt).scalars().all())
