"""预算仓储 — 只读查询。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import CategoryType, TransactionType

# 预算实际额计算时排除的交易类型
_BUDGET_EXCLUDED_TYPES = frozenset({
    TransactionType.BALANCE_ADJUSTMENT.value,
    TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT.value,
    TransactionType.RECEIVABLE_ADVANCE.value,
    TransactionType.RECEIVABLE_REPAYMENT.value,
    TransactionType.TRANSFER.value,
})


@dataclass(slots=True)
class BudgetLineWithActual:
    """预算明细行 + 实际发生额。"""

    line: BudgetLine
    category_name: str
    category_color: str | None
    actual_minor: int
    remaining_minor: int
    progress_pct: float  # 0.0 ~ 100.0+
    is_over: bool


@dataclass(slots=True)
class BudgetPeriodView:
    """预算期间完整视图。"""

    period: BudgetPeriod
    lines: list[BudgetLineWithActual]
    planned_total: int
    actual_total: int


class BudgetRepository:
    """预算数据访问。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── 期间查询 ──

    def get_period(self, year: int, month: int) -> BudgetPeriod | None:
        """获取指定年月的预算期间。"""
        return self._session.scalar(
            select(BudgetPeriod)
            .where(BudgetPeriod.year == year, BudgetPeriod.month == month)
        )

    def get_period_by_id(self, period_id: str) -> BudgetPeriod | None:
        """按 ID 获取预算期间。"""
        return self._session.get(BudgetPeriod, period_id)

    def list_periods(
        self, *, limit: int = 24
    ) -> list[BudgetPeriod]:
        """列出最近 N 个预算期间（按年月降序）。"""
        return list(
            self._session.scalars(
                select(BudgetPeriod)
                .order_by(BudgetPeriod.year.desc(), BudgetPeriod.month.desc())
                .limit(limit)
            )
        )

    def get_previous_period(
        self, year: int, month: int
    ) -> BudgetPeriod | None:
        """获取上一个月的预算期间。"""
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        return self.get_period(prev_year, prev_month)

    # ── 预算明细查询 ──

    def get_lines(self, period_id: str) -> list[BudgetLine]:
        """获取预算期间的所有明细行（按 sort_order 排序）。"""
        return list(
            self._session.scalars(
                select(BudgetLine)
                .where(BudgetLine.budget_period_id == period_id)
                .options(joinedload(BudgetLine.category))
                .order_by(BudgetLine.sort_order, BudgetLine.type, BudgetLine.created_at)
            )
        )

    def get_line(self, line_id: str) -> BudgetLine | None:
        """按 ID 获取预算明细行。"""
        return self._session.get(BudgetLine, line_id)

    # ── 实际发生额查询 ──

    def get_actual_by_category(
        self, year: int, month: int, category_id: str
    ) -> int:
        """获取指定分类在某月的实际发生额（分）。

        排除：balance_adjustment、historical_investment_settlement、
        receivable_advance、receivable_repayment、transfer。
        """
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        result = self._session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_minor), 0))
            .where(
                Transaction.category_id == category_id,
                Transaction.transaction_date >= start,
                Transaction.transaction_date < end,
                Transaction.type.not_in(_BUDGET_EXCLUDED_TYPES),
            )
        )
        return result or 0

    def get_actuals_for_period(
        self, year: int, month: int
    ) -> dict[str, int]:
        """获取所有分类在某月的实际发生额（分）。

        Returns:
            {category_id: amount_minor} 映射。
        """
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        rows = (
            self._session.execute(
                select(
                    Transaction.category_id,
                    func.coalesce(func.sum(Transaction.amount_minor), 0),
                )
                .where(
                    Transaction.transaction_date >= start,
                    Transaction.transaction_date < end,
                    Transaction.type.not_in(_BUDGET_EXCLUDED_TYPES),
                    Transaction.category_id.isnot(None),
                )
                .group_by(Transaction.category_id)
            )
        ).all()

        return {row[0]: row[1] for row in rows}

    # ── 视图构建 ──

    def build_period_view(
        self, year: int, month: int
    ) -> BudgetPeriodView | None:
        """构建预算期间完整视图（含实际发生额）。"""
        period = self.get_period(year, month)
        if period is None:
            return None

        lines = self.get_lines(period.id)
        actuals = self.get_actuals_for_period(year, month)

        planned_total = 0
        actual_total = 0
        line_views: list[BudgetLineWithActual] = []

        for line in lines:
            actual = actuals.get(line.category_id, 0)
            planned_total += line.amount_minor
            actual_total += actual
            remaining = line.amount_minor - actual

            if line.amount_minor > 0:
                progress = min(round(actual / line.amount_minor * 100, 1), 999.9)
            else:
                progress = 0.0

            line_views.append(BudgetLineWithActual(
                line=line,
                category_name=line.category.name if line.category else '未知',
                category_color=line.category.color if line.category else None,
                actual_minor=actual,
                remaining_minor=remaining,
                progress_pct=progress,
                is_over=actual > line.amount_minor,
            ))

        return BudgetPeriodView(
            period=period,
            lines=line_views,
            planned_total=planned_total,
            actual_total=actual_total,
        )

    # ── 类别查询 ──

    def get_expense_categories(self) -> list[Category]:
        """获取所有启用的支出分类。"""
        return list(
            self._session.scalars(
                select(Category)
                .where(Category.type == CategoryType.EXPENSE.value, Category.is_enabled.is_(True))
                .order_by(Category.sort_order, Category.name)
            )
        )

    def get_income_categories(self) -> list[Category]:
        """获取所有启用的收入分类。"""
        return list(
            self._session.scalars(
                select(Category)
                .where(Category.type == CategoryType.INCOME.value, Category.is_enabled.is_(True))
                .order_by(Category.sort_order, Category.name)
            )
        )
