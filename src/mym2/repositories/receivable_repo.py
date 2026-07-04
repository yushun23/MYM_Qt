"""应收仓储 — 应收相关只读查询。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType, TransactionType


@dataclass(slots=True)
class DebtorHistoryItem:
    """债务人历史记录项。"""

    transaction_id: str
    transaction_type: str
    transaction_date: date
    amount_minor: int
    note: str | None
    counter_account_name: str | None


class ReceivableRepository:
    """应收数据访问。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_receivable_accounts(self) -> list[Account]:
        """获取所有启用的 receivable 账户。"""
        return list(
            self._session.scalars(
                select(Account)
                .where(Account.type == AccountType.RECEIVABLE)
                .where(Account.is_enabled)
                .order_by(Account.name)
            )
        )

    def get_transactions_for_debtor(
        self,
        account_id: str,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Transaction]:
        """获取指定债务人的所有应收流水。"""
        from sqlalchemy import or_

        q = (
            select(Transaction)
            .where(
                or_(
                    Transaction.account_out_id == account_id,
                    Transaction.account_in_id == account_id,
                )
            )
            .where(
                Transaction.type.in_([
                    TransactionType.RECEIVABLE_ADVANCE,
                    TransactionType.RECEIVABLE_REPAYMENT,
                ])
            )
        )

        if date_from is not None:
            q = q.where(Transaction.transaction_date >= date_from)
        if date_to is not None:
            q = q.where(Transaction.transaction_date <= date_to)

        q = q.order_by(
            Transaction.transaction_date.desc(),
            Transaction.created_at.desc(),
            Transaction.id.desc(),
        )

        return list(self._session.scalars(q))

    def get_outstanding_balance(self, account_id: str) -> int:
        """获取应收账户当前未收回余额。"""
        account = self._session.get(Account, account_id)
        if account is None:
            return 0
        return account.current_balance_minor
