"""FinancialAnalysisService – queries for AI analysis and controlled canvas data (P31)."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text, case, extract
from sqlalchemy.orm import Session

from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.entities.budget import BudgetPeriod, BudgetLine
from mym.domain.enums import AccountType, TransactionStatus, CategoryType, BudgetStatus

logger = logging.getLogger(__name__)


# ── Canvas Data Types ────────────────────────────────────────────────────────

@dataclass
class CanvasMetricCard:
    """A single metric card for the canvas."""
    label: str
    value: str
    trend: str | None = None  # "up", "down", "flat", None
    change_pct: Decimal | None = None
    icon: str | None = None

    def to_dict(self) -> dict:
        d = {"type": "metric_card", "label": self.label, "value": self.value}
        if self.trend:
            d["trend"] = self.trend
        if self.change_pct is not None:
            d["change_pct"] = str(self.change_pct)
        if self.icon:
            d["icon"] = self.icon
        return d


@dataclass
class CanvasTable:
    """A data table for the canvas."""
    title: str
    columns: list[str]
    rows: list[list[str]]

    def to_dict(self) -> dict:
        return {
            "type": "table",
            "title": self.title,
            "columns": self.columns,
            "rows": self.rows,
        }


@dataclass
class CanvasChart:
    """A chart for the canvas – pie, line, bar."""
    title: str
    chart_type: str  # pie, line, bar
    labels: list[str]
    series: list[dict[str, Any]]  # [{"name": "...", "data": [...]}]

    def to_dict(self) -> dict:
        return {
            "type": "chart",
            "title": self.title,
            "chart_type": self.chart_type,
            "labels": self.labels,
            "series": self.series,
        }


@dataclass
class CanvasBlock:
    """A block of analysis text."""
    text: str = ""
    items: list[CanvasMetricCard] = field(default_factory=list)
    table: CanvasTable | None = None
    chart: CanvasChart | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"type": "analysis_block", "text": self.text}
        if self.items:
            d["items"] = [item.to_dict() for item in self.items]
        if self.table:
            d["table"] = self.table.to_dict()
        if self.chart:
            d["chart"] = self.chart.to_dict()
        return d


@dataclass
class CanvasResponse:
    """Controlled AI canvas response – no raw HTML."""
    title: str = ""
    blocks: list[CanvasBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canvas_version": "1.0",
            "title": self.title,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def validate(cls, data: dict) -> list[str]:
        """Validate canvas JSON. Returns list of error messages."""
        errors = []
        if data.get("canvas_version") != "1.0":
            errors.append("不支持的 canvas 版本")
        if "blocks" not in data:
            errors.append("缺少 blocks 字段")
        elif not isinstance(data["blocks"], list):
            errors.append("blocks 必须是数组")
        else:
            for i, block in enumerate(data["blocks"]):
                if not isinstance(block, dict):
                    errors.append(f"blocks[{i}] 必须是对象")
                    continue
                block_type = block.get("type")
                if block_type not in ("analysis_block", "metric_card", "table", "chart"):
                    errors.append(f"blocks[{i}] 不支持的类型: {block_type}")
        return errors


# ── Analysis Query Service ───────────────────────────────────────────────────

class FinancialAnalysisService:
    """Provides financial analysis data for AI consumption.

    All queries go through SQLAlchemy. AI only interprets results – it never
    fabricates data. Amounts and statistics must match ReportQueryService.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ── Monthly Summary ───────────────────────────────────────────────────

    def monthly_summary(self, year: int, month: int) -> dict[str, Any]:
        """Return income, expense, net for a specific month."""
        income = self._sum_by_type(year, month, CategoryType.INCOME)
        expense = self._sum_by_type(year, month, CategoryType.EXPENSE)
        net = income - expense
        return {
            "year": year,
            "month": month,
            "income": str(income),
            "expense": str(expense),
            "net": str(net),
        }

    def _sum_by_type(self, year: int, month: int, cat_type: CategoryType) -> Decimal:
        """Sum signed amounts for a given category type in a month."""
        from sqlalchemy import and_

        result = (
            self._session.query(func.coalesce(func.sum(TransactionLine.signed_amount), 0))
            .join(Transaction)
            .join(Category, TransactionLine.category_id == Category.id)
            .where(
                and_(
                    Transaction.status == TransactionStatus.POSTED,
                    extract("year", Transaction.transaction_date) == year,
                    extract("month", Transaction.transaction_date) == month,
                    Category.category_type == cat_type,
                )
            )
            .scalar()
        )
        return abs(Decimal(str(result))) if result else Decimal("0")

    # ── Category Breakdown ────────────────────────────────────────────────

    def category_breakdown(self, year: int, month: int) -> dict[str, Any]:
        """Return expense breakdown by category for a month."""
        rows = (
            self._session.query(
                Category.name,
                func.coalesce(func.sum(func.abs(TransactionLine.signed_amount)), 0),
            )
            .join(TransactionLine)
            .join(Transaction)
            .where(
                Transaction.status == TransactionStatus.POSTED,
                extract("year", Transaction.transaction_date) == year,
                extract("month", Transaction.transaction_date) == month,
                Category.category_type == CategoryType.EXPENSE,
            )
            .group_by(Category.name)
            .order_by(func.coalesce(func.sum(func.abs(TransactionLine.signed_amount)), 0).desc())
            .all()
        )
        categories = [
            {"name": r[0], "amount": str(r[1])}
            for r in rows
            if float(str(r[1])) > 0
        ]
        total = Decimal(
            str(sum(Decimal(c["amount"]) for c in categories))
        )
        return {"categories": categories, "total": str(total)}

    def income_breakdown(self, year: int, month: int) -> dict[str, Any]:
        """Return income breakdown by category for a month."""
        rows = (
            self._session.query(
                Category.name,
                func.coalesce(func.sum(func.abs(TransactionLine.signed_amount)), 0),
            )
            .join(TransactionLine)
            .join(Transaction)
            .where(
                Transaction.status == TransactionStatus.POSTED,
                extract("year", Transaction.transaction_date) == year,
                extract("month", Transaction.transaction_date) == month,
                Category.category_type == CategoryType.INCOME,
            )
            .group_by(Category.name)
            .order_by(func.coalesce(func.sum(func.abs(TransactionLine.signed_amount)), 0).desc())
            .all()
        )
        categories = [
            {"name": r[0], "amount": str(r[1])}
            for r in rows
            if float(str(r[1])) > 0
        ]
        return {"categories": categories}

    # ── Account Cash Flow ─────────────────────────────────────────────────

    def account_cashflow(self, year: int, month: int) -> list[dict]:
        """Cash flow per account for a month."""
        rows = (
            self._session.query(
                Account.name,
                func.coalesce(
                    func.sum(
                        case(
                            (TransactionLine.signed_amount > 0, TransactionLine.signed_amount),
                            else_=0,
                        )
                    ), 0
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (TransactionLine.signed_amount < 0, func.abs(TransactionLine.signed_amount)),
                            else_=0,
                        )
                    ), 0
                ),
            )
            .join(TransactionLine)
            .join(Transaction)
            .where(
                Transaction.status == TransactionStatus.POSTED,
                extract("year", Transaction.transaction_date) == year,
                extract("month", Transaction.transaction_date) == month,
                Account.account_type.in_([AccountType.ASSET, AccountType.LIABILITY]),
            )
            .group_by(Account.name)
            .all()
        )
        return [
            {"account": r[0], "inflow": str(r[1]), "outflow": str(r[2])}
            for r in rows
        ]

    # ── Budget Execution ──────────────────────────────────────────────────

    def budget_execution(self, year: int, month: int) -> dict[str, Any]:
        """Compare budget vs actual for a month."""
        budget_period = (
            self._session.query(BudgetPeriod)
            .where(
                BudgetPeriod.year == year,
                BudgetPeriod.month == month,
                BudgetPeriod.status == BudgetStatus.OPEN,
            )
            .first()
        )
        if not budget_period:
            return {"has_budget": False}

        items = (
            self._session.query(BudgetLine)
            .where(BudgetLine.period_id == budget_period.id)
            .all()
        )

        # Get actuals for this period
        actuals = {}
        for cat_type in (CategoryType.INCOME, CategoryType.EXPENSE):
            rows = (
                self._session.query(
                    Category.name,
                    func.coalesce(func.sum(func.abs(TransactionLine.signed_amount)), 0),
                )
                .join(TransactionLine)
                .join(Transaction)
                .where(
                    Transaction.status == TransactionStatus.POSTED,
                    extract("year", Transaction.transaction_date) == year,
                    extract("month", Transaction.transaction_date) == month,
                    Category.category_type == cat_type,
                )
                .group_by(Category.name)
                .all()
            )
            for r in rows:
                actuals[r[0]] = str(r[1])

        result_items = []
        for item in items:
            actual = Decimal(actuals.get(item.category_name, "0"))
            budgeted = Decimal(str(item.amount))
            result_items.append({
                "category": item.category_name,
                "budgeted": str(budgeted),
                "actual": str(actual),
                "difference": str(actual - budgeted),
                "pct_used": str(round((actual / budgeted * 100) if budgeted > 0 else 0, 1)),
            })

        return {
            "has_budget": True,
            "year": year,
            "month": month,
            "items": result_items,
        }

    # ── Anomaly Detection (simple) ────────────────────────────────────────

    def anomaly_detection(self, year: int, month: int) -> list[dict]:
        """Detect spending anomalies vs 3-month average."""
        current = self._category_totals(year, month, CategoryType.EXPENSE)
        anomalies = []

        for cat, curr_amt in current.items():
            # 3-month average
            avg = Decimal("0")
            count = 0
            for m in range(month - 3, month):
                ym = m if m > 0 else m + 12
                yy = year if m > 0 else year - 1
                prev = self._category_totals(yy, ym, CategoryType.EXPENSE)
                if cat in prev:
                    avg += prev[cat]
                    count += 1
            if count > 0:
                avg = avg / count
                if avg > 0 and curr_amt > avg * Decimal("1.5"):
                    anomalies.append({
                        "category": cat,
                        "current": str(curr_amt),
                        "average_3m": str(avg),
                        "excess_pct": str(round((curr_amt / avg - 1) * 100, 1)),
                    })

        return anomalies

    def _category_totals(self, year: int, month: int, cat_type: CategoryType) -> dict[str, Decimal]:
        rows = (
            self._session.query(
                Category.name,
                func.coalesce(func.sum(func.abs(TransactionLine.signed_amount)), 0),
            )
            .join(TransactionLine)
            .join(Transaction)
            .where(
                Transaction.status == TransactionStatus.POSTED,
                extract("year", Transaction.transaction_date) == year,
                extract("month", Transaction.transaction_date) == month,
                Category.category_type == cat_type,
            )
            .group_by(Category.name)
            .all()
        )
        return {r[0]: Decimal(str(r[1])) for r in rows}

    # ── Period Comparison ────────────────────────────────────────────────

    def period_comparison(self, year: int, month: int) -> dict[str, Any]:
        """Compare current month vs previous month and same month last year."""
        current = self.monthly_summary(year, month)

        # Previous month
        prev_m = month - 1
        prev_y = year
        if prev_m < 1:
            prev_m = 12
            prev_y = year - 1
        previous = self.monthly_summary(prev_y, prev_m)

        # Same month last year
        last_year = self.monthly_summary(year - 1, month)

        def _pct_change(curr_str: str, prev_str: str) -> str | None:
            c = Decimal(curr_str)
            p = Decimal(prev_str)
            if p == 0 and c == 0:
                return "0"
            if p == 0:
                return None
            return str(round((c / p - 1) * 100, 1))

        return {
            "current": current,
            "previous_month": previous,
            "same_month_last_year": last_year,
            "mom_change": {
                "income": _pct_change(current["income"], previous["income"]),
                "expense": _pct_change(current["expense"], previous["expense"]),
            },
            "yoy_change": {
                "income": _pct_change(current["income"], last_year["income"]),
                "expense": _pct_change(current["expense"], last_year["expense"]),
            },
        }

    # ── Recent Transactions ───────────────────────────────────────────────

    def recent_transactions(self, limit: int = 20) -> list[dict]:
        txs = (
            self._session.query(Transaction)
            .where(Transaction.status == TransactionStatus.POSTED)
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(limit)
            .all()
        )
        result = []
        for tx in txs:
            lines = []
            for line in tx.lines:
                lines.append({
                    "account_id": line.account_id,
                    "amount": str(line.signed_amount),
                    "memo": line.memo or "",
                })
            result.append({
                "id": tx.id,
                "date": tx.transaction_date.isoformat() if tx.transaction_date else "",
                "type": tx.business_type or "",
                "description": tx.description or "",
                "lines": lines,
            })
        return result

    # ── Full Analysis Dump ────────────────────────────────────────────────

    def full_analysis(self, year: int, month: int) -> dict[str, Any]:
        """Return all analysis data for one call."""
        return {
            "monthly_summary": self.monthly_summary(year, month),
            "category_breakdown": self.category_breakdown(year, month),
            "income_breakdown": self.income_breakdown(year, month),
            "account_cashflow": self.account_cashflow(year, month),
            "budget_execution": self.budget_execution(year, month),
            "anomaly_detection": self.anomaly_detection(year, month),
            "period_comparison": self.period_comparison(year, month),
            "recent_transactions": self.recent_transactions(10),
        }
