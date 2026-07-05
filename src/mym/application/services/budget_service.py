"""BudgetService – business logic for budget creation, management, and analysis."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from mym.domain.entities.budget import BudgetPeriod, BudgetLine
from mym.domain.enums import BudgetStatus
from mym.infrastructure.repositories.budget_repo import BudgetRepository

logger = logging.getLogger(__name__)


@dataclass
class BudgetActuals:
    """Actual income/expense values for a budget period."""

    total_income: Decimal = Decimal("0")
    total_expense: Decimal = Decimal("0")
    by_category: dict[int, Decimal] = field(default_factory=dict)


@dataclass
class BudgetLineSummary:
    """Summary of a budget line with planned vs actual."""

    id: int
    name: str
    budget_type: str
    planned_amount: Decimal
    actual_amount: Decimal
    is_group: bool = False
    parent_id: int | None = None
    category_id: int | None = None
    execution_pct: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    is_over_budget: bool = False
    warn_threshold_pct: int | None = None
    children: list["BudgetLineSummary"] = field(default_factory=list)
    sort_order: int = 0

    def __post_init__(self):
        if self.planned_amount > 0:
            self.execution_pct = round(
                self.actual_amount / self.planned_amount * 100, 1
            )
        self.remaining = self.planned_amount - self.actual_amount
        if self.warn_threshold_pct:
            self.is_over_budget = self.execution_pct >= self.warn_threshold_pct
        else:
            self.is_over_budget = self.actual_amount > self.planned_amount


@dataclass
class BudgetOperationResult:
    """Result of a budget operation."""

    success: bool
    period_id: int | None = None
    line_id: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BudgetService:
    """Service for all budget-related operations."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = BudgetRepository(session)

    # --- Period Management ---

    def create_period(
        self, year: int, month: int, notes: str | None = None
    ) -> BudgetOperationResult:
        """Create a new budget period for a specific month."""
        existing = self._repo.get_period_by_ym(year, month)
        if existing:
            return BudgetOperationResult(
                success=False,
                errors=[f"{year}-{month:02d} 的预算已存在"],
            )
        period = BudgetPeriod(
            year=year,
            month=month,
            status=BudgetStatus.OPEN,
            notes=notes,
        )
        self._repo.add_period(period)
        self._session.flush()
        logger.info("Budget period created: %s", period.period_label)
        return BudgetOperationResult(success=True, period_id=period.id)

    def copy_from_month(
        self, from_year: int, from_month: int, to_year: int, to_month: int
    ) -> BudgetOperationResult:
        """Copy budget structure from one month to another."""
        source = self._repo.get_period_by_ym(from_year, from_month)
        if not source:
            return BudgetOperationResult(
                success=False,
                errors=[f"源月份 {from_year}-{from_month:02d} 无预算数据"],
            )

        existing = self._repo.get_period_by_ym(to_year, to_month)
        if existing:
            return BudgetOperationResult(
                success=False,
                errors=[f"目标月份 {to_year}-{to_month:02d} 已有预算"],
            )

        target = BudgetPeriod(
            year=to_year,
            month=to_month,
            status=BudgetStatus.OPEN,
            notes=f"从 {from_year}-{from_month:02d} 复制",
        )
        self._repo.add_period(target)
        self._session.flush()

        # Copy lines recursively
        root_lines = self._repo.get_root_lines(source.id)
        self._copy_lines(root_lines, target.id, None)
        logger.info(
            "Budget copied: %d-%02d → %d-%02d",
            from_year, from_month, to_year, to_month,
        )
        return BudgetOperationResult(success=True, period_id=target.id)

    def _copy_lines(
        self, source_lines: list[BudgetLine],
        new_period_id: int, new_parent_id: int | None,
    ) -> None:
        """Recursively copy budget lines to a new period."""
        for src in source_lines:
            new_line = BudgetLine(
                period_id=new_period_id,
                parent_id=new_parent_id,
                category_id=src.category_id,
                budget_type=src.budget_type,
                name=src.name,
                planned_amount=src.planned_amount,
                sort_order=src.sort_order,
                is_group=src.is_group,
                warn_threshold_pct=src.warn_threshold_pct,
            )
            self._repo.add_line(new_line)
            self._session.flush()

            children = self._repo.get_children(src.id)
            if children:
                self._copy_lines(children, new_period_id, new_line.id)

    def close_period(self, period_id: int) -> BudgetOperationResult:
        """Close a budget period – freeze it."""
        period = self._repo.get_period(period_id)
        if not period:
            return BudgetOperationResult(success=False, errors=["预算月份不存在"])
        if period.status == BudgetStatus.CLOSED:
            return BudgetOperationResult(success=False, errors=["该月份已关闭"])

        self._repo.update_period_status(
            period_id, BudgetStatus.CLOSED, datetime.utcnow()
        )
        logger.info("Budget period closed: %s", period.period_label)
        return BudgetOperationResult(success=True, period_id=period_id)

    def reopen_period(self, period_id: int) -> BudgetOperationResult:
        """Reopen a closed budget period."""
        period = self._repo.get_period(period_id)
        if not period:
            return BudgetOperationResult(success=False, errors=["预算月份不存在"])
        if period.status == BudgetStatus.OPEN:
            return BudgetOperationResult(success=False, errors=["该月份已经开启"])

        self._repo.update_period_status(period_id, BudgetStatus.OPEN)
        logger.info("Budget period reopened: %s", period.period_label)
        return BudgetOperationResult(success=True, period_id=period_id)

    def delete_period(self, period_id: int) -> BudgetOperationResult:
        """Delete a budget period and all its lines."""
        period = self._repo.get_period(period_id)
        if not period:
            return BudgetOperationResult(success=False, errors=["预算月份不存在"])
        self._repo.delete_period(period_id)
        logger.info("Budget period deleted: %s", period.period_label)
        return BudgetOperationResult(success=True)

    # --- Line Management ---

    def add_line(
        self,
        period_id: int,
        name: str,
        budget_type: str,
        planned_amount: Decimal,
        parent_id: int | None = None,
        category_id: int | None = None,
        is_group: bool = False,
        warn_threshold_pct: int | None = None,
        sort_order: int = 0,
    ) -> BudgetOperationResult:
        """Add a budget line to a period."""
        period = self._repo.get_period(period_id)
        if not period:
            return BudgetOperationResult(success=False, errors=["预算月份不存在"])
        if period.status == BudgetStatus.CLOSED:
            return BudgetOperationResult(
                success=False,
                errors=["已关闭月份不允许修改预算"],
            )

        if budget_type not in ("income", "expense"):
            return BudgetOperationResult(
                success=False,
                errors=[f"无效的预算类型: {budget_type}"],
            )

        line = BudgetLine(
            period_id=period_id,
            parent_id=parent_id,
            category_id=category_id,
            budget_type=budget_type,
            name=name,
            planned_amount=planned_amount,
            sort_order=sort_order,
            is_group=is_group,
            warn_threshold_pct=warn_threshold_pct,
        )
        self._repo.add_line(line)
        self._session.flush()
        return BudgetOperationResult(success=True, line_id=line.id)

    def update_line_planned(self, line_id: int, planned_amount: Decimal) -> BudgetOperationResult:
        """Update the planned amount of a budget line."""
        line = self._repo.get_line(line_id)
        if not line:
            return BudgetOperationResult(success=False, errors=["预算行不存在"])

        period = self._repo.get_period(line.period_id)
        if period and period.status == BudgetStatus.CLOSED:
            return BudgetOperationResult(
                success=False,
                errors=["已关闭月份不允许修改预算"],
            )

        self._repo.update_line_planned(line_id, planned_amount)
        return BudgetOperationResult(success=True, line_id=line_id)

    def delete_line(self, line_id: int) -> BudgetOperationResult:
        """Delete a budget line (and its children)."""
        line = self._repo.get_line(line_id)
        if not line:
            return BudgetOperationResult(success=False, errors=["预算行不存在"])

        period = self._repo.get_period(line.period_id)
        if period and period.status == BudgetStatus.CLOSED:
            return BudgetOperationResult(
                success=False,
                errors=["已关闭月份不允许删除预算行"],
            )

        self._repo.delete_line(line_id)
        return BudgetOperationResult(success=True)

    # --- Query ---

    def get_period_summary(
        self, period_id: int, actuals: BudgetActuals | None = None
    ) -> list[BudgetLineSummary]:
        """Get budget vs actual summary for a period, optionally with actuals."""
        lines = self._repo.get_lines_by_period(period_id)
        line_map: dict[int, BudgetLineSummary] = {}

        # First pass: create all summaries
        for line in lines:
            cat_actual = Decimal("0")
            if actuals and line.category_id and not line.is_group:
                cat_actual = actuals.by_category.get(line.category_id, Decimal("0"))

            summary = BudgetLineSummary(
                id=line.id,
                name=line.name,
                budget_type=line.budget_type,
                planned_amount=line.planned_amount,
                actual_amount=cat_actual,
                is_group=line.is_group,
                parent_id=line.parent_id,
                category_id=line.category_id,
                warn_threshold_pct=line.warn_threshold_pct,
                sort_order=line.sort_order,
            )
            line_map[line.id] = summary

        # Second pass: roll up children into parents and build tree
        roots: list[BudgetLineSummary] = []
        for summary in line_map.values():
            if summary.parent_id and summary.parent_id in line_map:
                parent = line_map[summary.parent_id]
                parent.children.append(summary)
                if summary.is_group:
                    # Roll up group actual amounts
                    parent.actual_amount += summary.actual_amount
                else:
                    parent.actual_amount += summary.actual_amount
            else:
                roots.append(summary)

        # Recalculate parent stats
        for summary in line_map.values():
            if summary.is_group and summary.planned_amount > 0:
                summary.execution_pct = round(
                    summary.actual_amount / summary.planned_amount * 100, 1
                )
                summary.remaining = summary.planned_amount - summary.actual_amount

        roots.sort(key=lambda x: x.sort_order)
        return roots

    def get_total_planned(
        self, period_id: int, budget_type: str
    ) -> Decimal:
        """Get total planned amount for a type."""
        return self._repo.get_total_planned(period_id, budget_type)

    def get_all_periods(
        self, year: int | None = None
    ) -> list[dict]:
        """List all budget periods with summary."""
        periods = self._repo.list_periods(year=year)
        result = []
        for p in periods:
            income = self._repo.get_total_planned(p.id, "income")
            expense = self._repo.get_total_planned(p.id, "expense")
            result.append({
                "id": p.id,
                "year": p.year,
                "month": p.month,
                "label": p.period_label,
                "status": p.status,
                "closed_at": str(p.closed_at) if p.closed_at else None,
                "planned_income": str(income),
                "planned_expense": str(expense),
                "notes": p.notes,
            })
        return result
