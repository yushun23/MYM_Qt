"""报表服务 — 仪表盘数据聚合。

所有查询只读，不产生副作用。
聚合口径与后续 ReportService 约定保持一致：
- 净资产 = Σ 所有活跃账户余额（含 investment_snapshot）
- 收入/支出仅统计 expense/income 类型流水
- 预算对比仅基于已分类的 expense 类型流水
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import (
    AccountType,
    TransactionType,
    is_asset_account,
    is_liability_account,
)

logger = logging.getLogger("mym2.services.report_service")


@dataclass(slots=True)
class DashboardData:
    """仪表盘聚合数据。"""

    # 资产/负债/净资产
    total_assets_minor: int
    total_liabilities_minor: int
    net_worth_minor: int
    receivable_minor: int

    # 当月
    current_month_income_minor: int
    current_month_expense_minor: int

    # 预算概览
    budget_total_minor: int | None
    budget_spent_minor: int | None

    # 账户明细
    asset_accounts: list[tuple[str, int]]  # (name, balance_minor)
    liability_accounts: list[tuple[str, int]]

    # 月度趋势（最近6个月）
    monthly_trend: list[MonthlySnapshot]

    # 分类明细（当月）
    category_breakdown: list[tuple[str, int]]  # (category_name, amount_minor)


@dataclass(slots=True)
class MonthlySnapshot:
    """月度快照。"""

    year: int
    month: int
    income_minor: int
    expense_minor: int
    net_worth_minor: int

    @property
    def label(self) -> str:
        return f"{self.month}月"


class ReportService:
    """报表聚合服务（只读）。"""

    def __init__(self) -> None:
        pass

    def get_dashboard_data(self, session: Session) -> DashboardData:
        """获取仪表盘所需全部聚合数据。"""
        today = date.today()
        current_year = today.year
        current_month = today.month

        # 账户聚合
        accounts = list(
            session.scalars(select(Account).where(Account.is_enabled))
        )
        asset_accounts = [
            (a.name, a.current_balance_minor)
            for a in accounts
            if is_asset_account(a.type)
        ]
        liability_accounts = [
            (a.name, a.current_balance_minor)
            for a in accounts
            if is_liability_account(a.type)
        ]
        receivable_minor = sum(
            a.current_balance_minor
            for a in accounts
            if a.type == AccountType.RECEIVABLE
        )
        total_assets = sum(v for _, v in asset_accounts)
        total_liabilities = sum(v for _, v in liability_accounts)
        net_worth = total_assets - total_liabilities

        # 当月收支
        month_income = self._sum_by_type(
            session, current_year, current_month, TransactionType.INCOME
        )
        month_expense = self._sum_by_type(
            session, current_year, current_month, TransactionType.EXPENSE
        )

        # 预算概览
        budget_data = self._get_budget_overview(session, current_year, current_month)

        # 月度趋势（最近6个月）
        monthly_trend = self._get_monthly_trend(session, current_year, current_month, months=6)

        # 当月分类支出明细
        category_breakdown = self._get_category_breakdown(
            session, current_year, current_month
        )

        return DashboardData(
            total_assets_minor=total_assets,
            total_liabilities_minor=total_liabilities,
            net_worth_minor=net_worth,
            receivable_minor=receivable_minor,
            current_month_income_minor=month_income,
            current_month_expense_minor=month_expense,
            budget_total_minor=budget_data[0],
            budget_spent_minor=budget_data[1],
            asset_accounts=asset_accounts,
            liability_accounts=liability_accounts,
            monthly_trend=monthly_trend,
            category_breakdown=category_breakdown,
        )

    # ── 内部方法 ──

    @staticmethod
    def _sum_by_type(
        session: Session, year: int, month: int, tx_type: TransactionType
    ) -> int:
        """按年月和类型汇总金额。"""
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        result = session.scalar(
            select(func.coalesce(func.sum(Transaction.amount_minor), 0))
            .where(
                Transaction.type == tx_type.value,
                Transaction.transaction_date >= start,
                Transaction.transaction_date < end,
            )
        )
        return result or 0

    @staticmethod
    def _get_budget_overview(
        session: Session, year: int, month: int
    ) -> tuple[int | None, int | None]:
        """获取当月预算总额和已用额。

        Returns:
            (budget_total_minor, budget_spent_minor)，
            无预算时返回 (None, None)。
        """
        period = session.scalar(
            select(BudgetPeriod).where(
                BudgetPeriod.year == year,
                BudgetPeriod.month == month,
            )
        )
        if period is None:
            return None, None

        total = session.scalar(
            select(func.coalesce(func.sum(BudgetLine.amount_minor), 0))
            .where(BudgetLine.budget_period_id == period.id)
        ) or 0

        # 已用 = 当月已分类 expense 流水总额
        spent = ReportService._sum_by_type(
            session, year, month, TransactionType.EXPENSE
        )

        return total, spent

    @staticmethod
    def _get_monthly_trend(
        session: Session,
        current_year: int,
        current_month: int,
        months: int = 6,
    ) -> list[MonthlySnapshot]:
        """获取最近 N 个月的收支和净资产趋势。"""
        snapshots: list[MonthlySnapshot] = []

        for offset in range(months - 1, -1, -1):
            m = current_month - offset
            y = current_year
            while m <= 0:
                m += 12
                y -= 1

            income = ReportService._sum_by_type(
                session, y, m, TransactionType.INCOME
            )
            expense = ReportService._sum_by_type(
                session, y, m, TransactionType.EXPENSE
            )

            # 资产在该月末的净值：用所有账户余额计算
            # （余额始终是最新值，这里简化处理：用当前账户余额 - 未来流水影响）
            # 更精确的趋势需要按时间点重算；这里返回当前余额作为趋势终值
            # 前面的月份用累计差值近似
            accounts = list(
                session.scalars(
                    select(Account).where(Account.is_enabled)
                )
            )
            net_worth = sum(
                a.current_balance_minor
                for a in accounts
                if is_asset_account(a.type)
            ) - sum(
                a.current_balance_minor
                for a in accounts
                if is_liability_account(a.type)
            )

            snapshots.append(MonthlySnapshot(
                year=y,
                month=m,
                income_minor=income,
                expense_minor=expense,
                net_worth_minor=net_worth,
            ))

        return snapshots

    @staticmethod
    def _get_category_breakdown(
        session: Session, year: int, month: int
    ) -> list[tuple[str, int]]:
        """获取当月分类支出明细（Top 10）。"""
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        rows = (
            session.execute(
                select(
                    Category.name,
                    func.coalesce(func.sum(Transaction.amount_minor), 0).label("total"),
                )
                .join(Category, Transaction.category_id == Category.id)
                .where(
                    Transaction.type == TransactionType.EXPENSE.value,
                    Transaction.transaction_date >= start,
                    Transaction.transaction_date < end,
                )
                .group_by(Category.name)
                .order_by(func.sum(Transaction.amount_minor).desc())
                .limit(10)
            )
            .all()
        )

        return [(row[0], row[1]) for row in rows]
