"""DTOs for report queries."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass
class ReportPeriodDTO:
    """Time period for a report query."""
    start_date: date
    end_date: date


@dataclass
class IncomeExpenseSummary:
    """Summary result for income/expense report."""
    total_income: Decimal = Decimal("0")
    total_expense: Decimal = Decimal("0")
    net_balance: Decimal = Decimal("0")
    transaction_count: int = 0
    monthly_trend: list[dict] = field(default_factory=list)
    category_breakdown_income: list[dict] = field(default_factory=list)
    category_breakdown_expense: list[dict] = field(default_factory=list)
    transaction_details: list[dict] = field(default_factory=list)


@dataclass
class BalanceSheetSnapshot:
    """Balance sheet at a specific as-of date."""
    as_of_date: date
    total_assets: Decimal = Decimal("0")
    total_liabilities: Decimal = Decimal("0")
    net_worth: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")
    receivable_balance: Decimal = Decimal("0")
    investment_estimated: Decimal = Decimal("0")
    account_groups: list[dict] = field(default_factory=list)
    liability_groups: list[dict] = field(default_factory=list)
    investment_valuation_warning: str = ""


@dataclass
class ReportFilter:
    """Filter parameters for income/expense reports."""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    account_ids: Optional[list[int]] = None
    category_ids: Optional[list[int]] = None
    business_types: Optional[list[str]] = None
    exclude_system: bool = True
