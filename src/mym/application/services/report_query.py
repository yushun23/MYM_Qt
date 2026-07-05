"""ReportQueryService – read-only queries for income/expense reports."""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mym.application.dto.report_dto import IncomeExpenseSummary, ReportFilter, ReportPeriodDTO
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import AccountType, CategoryType, TransactionRole, TransactionStatus

logger = logging.getLogger(__name__)

# Business types mapped to income/expense for reporting
_INCOME_TYPES = {"income", "stock_profit", "recover"}
_EXPENSE_TYPES = {"expense", "stock_loss", "lend", "balance_adjustment"}

# Business types that should be excluded from real income/expense stats
_EXCLUDE_FROM_STATS = {"transfer"}


class ReportQueryService:
    """Read-only service for report generation. No DB writes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_income_expense_report(
        self,
        period: ReportPeriodDTO,
        account_ids: list[int] | None = None,
        category_ids: list[int] | None = None,
    ) -> IncomeExpenseSummary:
        """Generate income/expense report for a given period."""
        summary = IncomeExpenseSummary()

        # Base query: posted transactions in date range
        base_query = (
            select(Transaction)
            .where(
                Transaction.status == TransactionStatus.POSTED,
                Transaction.transaction_date >= period.start_date,
                Transaction.transaction_date <= period.end_date,
                Transaction.business_type.not_in(list(_EXCLUDE_FROM_STATS)),
            )
        )

        if account_ids:
            # Filter by account via TransactionLines
            tx_ids_sub = (
                select(TransactionLine.transaction_id.distinct())
                .where(TransactionLine.account_id.in_(account_ids))
                .subquery()
            )
            base_query = base_query.where(Transaction.id.in_(select(tx_ids_sub)))

        transactions = self._session.execute(
            base_query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        ).scalars().all()

        summary.transaction_count = len(transactions)

        # Aggregate totals
        income_total = Decimal("0")
        expense_total = Decimal("0")
        tx_details: list[dict] = []

        for tx in transactions:
            tx_amount = Decimal("0")
            for line in tx.lines:
                if line.role == "debit":
                    tx_amount += line.signed_amount

            if tx.business_type in _INCOME_TYPES:
                income_total += tx_amount
            elif tx.business_type in _EXPENSE_TYPES:
                expense_total += tx_amount

            tx_details.append({
                "id": tx.id,
                "date": str(tx.transaction_date),
                "business_type": tx.business_type,
                "amount": str(tx_amount),
                "description": tx.description or "",
                "status": str(tx.status),
            })

        summary.total_income = income_total
        summary.total_expense = expense_total
        summary.net_balance = income_total - expense_total
        summary.transaction_details = tx_details

        # Monthly trend (all months in the period)
        months = self._months_in_period(period.start_date, period.end_date)
        summary.monthly_trend = []
        for m_start, m_end, m_label in months:
            m_income = Decimal("0")
            m_expense = Decimal("0")
            for tx in transactions:
                if m_start <= tx.transaction_date <= m_end:
                    tx_amt = Decimal("0")
                    for line in tx.lines:
                        if line.role == "debit":
                            tx_amt += line.signed_amount
                    if tx.business_type in _INCOME_TYPES:
                        m_income += tx_amt
                    elif tx.business_type in _EXPENSE_TYPES:
                        m_expense += tx_amt
            summary.monthly_trend.append({
                "month": m_label,
                "income": str(m_income),
                "expense": str(m_expense),
                "net": str(m_income - m_expense),
            })

        # Category breakdown
        summary.category_breakdown_income = self._category_breakdown(
            transactions, _INCOME_TYPES
        )
        summary.category_breakdown_expense = self._category_breakdown(
            transactions, _EXPENSE_TYPES
        )

        return summary

    def _category_breakdown(
        self, transactions: list[Transaction], biz_types: set[str]
    ) -> list[dict]:
        """Compute category-level breakdown for given business types."""
        cat_totals: dict[str, Decimal] = {}
        cat_map: dict[int, str] = {}

        # Preload all categories
        cats = self._session.execute(select(Category)).scalars().all()
        for c in cats:
            cat_map[c.id] = c.name

        for tx in transactions:
            if tx.business_type not in biz_types:
                continue
            for line in tx.lines:
                if line.role != "debit":
                    continue
                cat_name = cat_map.get(line.category_id, "未分类") if line.category_id else "未分类"
                cat_totals[cat_name] = cat_totals.get(cat_name, Decimal("0")) + line.signed_amount

        return sorted(
            [{"name": k, "value": str(v)} for k, v in cat_totals.items() if v > 0],
            key=lambda x: Decimal(x["value"]),
            reverse=True,
        )

    @staticmethod
    def _months_in_period(start: date, end: date) -> list[tuple[date, date, str]]:
        """Generate list of (month_start, month_end, label) for the period."""
        months = []
        current = date(start.year, start.month, 1)
        while current <= end:
            if current.month == 12:
                next_month = date(current.year + 1, 1, 1)
            else:
                next_month = date(current.year, current.month + 1, 1)
            month_end = min(next_month - timedelta(days=1), end)
            months.append((
                max(current, start),
                month_end,
                f"{current.year}-{current.month:02d}",
            ))
            current = next_month
        return months
