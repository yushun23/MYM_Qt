"""DashboardQueryService – read-only queries for the dashboard."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mym.domain.entities.account import Account
from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import AccountType, TransactionStatus


@dataclass
class DashboardSummary:
    """Aggregated dashboard data."""

    total_assets: Decimal = Decimal("0")
    total_liabilities: Decimal = Decimal("0")
    net_worth: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")
    receivable_balance: Decimal = Decimal("0")
    recent_transactions: list[dict] = field(default_factory=list)
    monthly_trend: list[dict] = field(default_factory=list)
    income_this_month: Decimal = Decimal("0")
    expense_this_month: Decimal = Decimal("0")


class DashboardQueryService:
    """Read-only service for dashboard data. No DB writes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_summary(self) -> DashboardSummary:
        """Build the full dashboard summary."""
        summary = DashboardSummary()

        # Account balances
        accounts = self._session.execute(
            select(Account).where(
                Account.is_deleted == False,  # noqa: E712
                Account.is_archived == False,  # noqa: E712
            )
        ).scalars().all()

        for acc in accounts:
            bal = acc.current_balance
            if acc.account_type == AccountType.LIABILITY:
                summary.total_liabilities += abs(bal)
            elif acc.account_type == AccountType.RECEIVABLE:
                summary.receivable_balance += bal
            elif acc.account_type == AccountType.INVESTMENT_LINKED:
                # Investment-linked accounts tracked separately
                pass
            else:
                summary.total_assets += bal

        summary.net_worth = summary.total_assets - summary.total_liabilities

        # Cash balance: sum of all ASSET type account balances
        cash_accs = [a for a in accounts if a.account_type == AccountType.ASSET]
        summary.cash_balance = sum(a.current_balance for a in cash_accs)

        # Recent transactions
        recent_txs = self._session.execute(
            select(Transaction)
            .where(Transaction.status == TransactionStatus.POSTED)
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(10)
        ).scalars().all()

        summary.recent_transactions = []
        for tx in recent_txs:
            total = Decimal("0")
            for line in tx.lines:
                if line.role == "debit":
                    total += line.signed_amount
            summary.recent_transactions.append({
                "id": tx.id,
                "date": str(tx.transaction_date),
                "type": tx.business_type,
                "amount": total,
                "description": tx.description or "",
            })

        # Monthly trend (last 6 months)
        today = date.today()
        for i in range(5, -1, -1):
            month_start = date(today.year, today.month, 1)
            for _ in range(i):
                month_start = (month_start.replace(day=1) - timedelta(days=1)).replace(day=1)
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

            month_txs = self._session.execute(
                select(Transaction).where(
                    Transaction.status == TransactionStatus.POSTED,
                    Transaction.transaction_date >= month_start,
                    Transaction.transaction_date <= month_end,
                )
            ).scalars().all()

            income = Decimal("0")
            expense = Decimal("0")
            for tx in month_txs:
                for line in tx.lines:
                    if line.role == "debit":
                        if tx.business_type in ("income", "stock_profit"):
                            income += line.signed_amount
                        elif tx.business_type in ("expense", "stock_loss"):
                            expense += line.signed_amount

            summary.monthly_trend.append({
                "month": f"{month_start.year}-{month_start.month:02d}",
                "income": income,
                "expense": expense,
            })

            if i == 0:
                summary.income_this_month = income
                summary.expense_this_month = expense

        return summary
