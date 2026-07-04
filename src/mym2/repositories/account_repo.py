"""账户仓储 — 只读查询 + 余额更新。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mym2.db.models.account import Account


class AccountRepository:
    """账户数据访问。

    查询方法与余额批量更新方法。
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, account_id: str) -> Account | None:
        """按主键获取账户。"""
        return self._session.get(Account, account_id)

    def get_all(self) -> list[Account]:
        """获取所有账户。"""
        return list(
            self._session.scalars(select(Account).order_by(Account.name))
        )

    def get_by_ids(self, account_ids: list[str]) -> list[Account]:
        """按 ID 列表批量获取账户。"""
        return list(
            self._session.scalars(
                select(Account).where(Account.id.in_(account_ids))
            )
        )

    def update_balance(self, account_id: str, new_balance_minor: int) -> None:
        """直接更新账户余额（在事务中调用）。

        Args:
            account_id: 账户 ID。
            new_balance_minor: 新余额（整数分）。
        """
        self._session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(current_balance_minor=new_balance_minor)
        )
