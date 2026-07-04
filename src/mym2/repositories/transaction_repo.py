"""流水仓储 — 只读查询（筛选、排序、分页）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction


@dataclass(slots=True)
class TransactionFilter:
    """流水筛选条件。"""

    date_from: date | None = None
    date_to: date | None = None
    account_ids: list[str] | None = None
    category_ids: list[str] | None = None
    types: list[str] | None = None
    keyword: str | None = None
    is_cleared: bool | None = None


@dataclass(slots=True)
class TransactionPage:
    """分页结果。"""

    items: list[Transaction]
    total: int
    page: int
    page_size: int


class TransactionRepository:
    """流水数据访问。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, transaction_id: str) -> Transaction | None:
        """按主键获取流水。"""
        return self._session.get(Transaction, transaction_id)

    def query_filtered(
        self,
        filters: TransactionFilter,
        *,
        page: int = 1,
        page_size: int = 50,
        sort_column: str = "transaction_date",
        sort_desc: bool = False,
    ) -> TransactionPage:
        """按筛选条件查询流水（稳定排序 + 分页）。

        稳定排序：同一天内按 created_at 次排序，再按 id 第三次排序。

        Args:
            filters: 筛选条件。
            page: 页码（从 1 开始）。
            page_size: 每页条数。
            sort_column: 排序主列（transaction_date 或 amount_minor）。
            sort_desc: 是否降序。

        Returns:
            TransactionPage 包含当前页数据、总数、页码、每页条数。
        """
        q = select(Transaction)

        # 筛选
        q = self._apply_filters(q, filters)

        total = self.count_filtered(filters)

        # 稳定排序：主列 → created_at → id
        col = getattr(Transaction, sort_column, Transaction.transaction_date)
        if sort_desc:
            q = q.order_by(col.desc(), Transaction.created_at.asc(), Transaction.id.asc())
        else:
            q = q.order_by(col.asc(), Transaction.created_at.asc(), Transaction.id.asc())

        # 分页
        offset = (page - 1) * page_size
        q = q.offset(offset).limit(page_size)

        items = list(self._session.scalars(q))
        return TransactionPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    def count_filtered(self, filters: TransactionFilter) -> int:
        """返回筛选条件下的流水总数。"""
        q = self._apply_filters(select(Transaction.id), filters)
        count_q = select(func.count()).select_from(q.subquery())
        return int(self._session.scalar(count_q) or 0)

    def _apply_filters(self, q: Any, filters: TransactionFilter) -> Any:
        if filters.date_from:
            q = q.where(Transaction.transaction_date >= filters.date_from)
        if filters.date_to:
            q = q.where(Transaction.transaction_date <= filters.date_to)
        if filters.account_ids:
            q = q.where(
                or_(
                    Transaction.account_out_id.in_(filters.account_ids),
                    Transaction.account_in_id.in_(filters.account_ids),
                )
            )
        if filters.category_ids:
            q = q.where(Transaction.category_id.in_(filters.category_ids))
        if filters.types:
            q = q.where(Transaction.type.in_(filters.types))
        if filters.keyword:
            pattern = f"%{filters.keyword}%"
            q = q.where(
                or_(
                    Transaction.note.ilike(pattern),
                    Transaction.id.ilike(pattern),
                )
            )
        if filters.is_cleared is not None:
            q = q.where(Transaction.is_cleared == filters.is_cleared)
        return q

    def sum_amounts_for_account(self, account_id: str) -> int:
        """计算某账户所有流水的 amount_minor 代数和。

        注意：此处返回原始代数和，不做方向调整。
        方向处理由 BalanceService 负责。

        Args:
            account_id: 账户 ID。

        Returns:
            所有流水的 amount_minor 代数和（分）。
        """
        # 作为 out 账户的流水
        out_sum = self._session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_minor), 0))
            .where(Transaction.account_out_id == account_id)
        ) or 0

        # 作为 in 账户的流水
        in_sum = self._session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_minor), 0))
            .where(Transaction.account_in_id == account_id)
        ) or 0

        return out_sum + in_sum

    def get_accounts_map(self) -> dict[str, Account]:
        """获取所有账户的 id→Account 映射（供 UI 显示用）。"""
        accounts = list(self._session.scalars(select(Account)))
        return {a.id: a for a in accounts}

    def get_categories_map(self) -> dict[str, Category]:
        """获取所有分类的 id→Category 映射（供 UI 显示用）。"""
        categories = list(self._session.scalars(select(Category)))
        return {c.id: c for c in categories}
