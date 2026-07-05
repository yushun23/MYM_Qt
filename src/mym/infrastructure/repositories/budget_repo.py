"""Budget repository – managed BudgetPeriod and BudgetLine persistence."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session, joinedload

from mym.domain.entities.budget import BudgetPeriod, BudgetLine
from mym.domain.enums import BudgetStatus


class BudgetRepository:
    """Repository for budget domain entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- Period ---

    def get_period(self, period_id: int) -> BudgetPeriod | None:
        return self._session.get(BudgetPeriod, period_id)

    def get_period_by_ym(self, year: int, month: int) -> BudgetPeriod | None:
        stmt = (
            select(BudgetPeriod)
            .where(
                BudgetPeriod.year == year,
                BudgetPeriod.month == month,
            )
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_periods(
        self, year: int | None = None, status: BudgetStatus | None = None
    ) -> list[BudgetPeriod]:
        stmt = select(BudgetPeriod)
        if year is not None:
            stmt = stmt.where(BudgetPeriod.year == year)
        if status is not None:
            stmt = stmt.where(BudgetPeriod.status == status)
        stmt = stmt.order_by(BudgetPeriod.year.desc(), BudgetPeriod.month.desc())
        return list(self._session.execute(stmt).scalars().all())

    def add_period(self, period: BudgetPeriod) -> None:
        self._session.add(period)

    def update_period_status(
        self, period_id: int, status: BudgetStatus, closed_at: datetime | None = None
    ) -> None:
        values = {"status": status}
        if closed_at is not None:
            values["closed_at"] = closed_at
        self._session.execute(
            update(BudgetPeriod)
            .where(BudgetPeriod.id == period_id)
            .values(**values)
        )

    def delete_period(self, period_id: int) -> None:
        period = self.get_period(period_id)
        if period:
            self._session.delete(period)

    def get_period_with_lines(self, period_id: int) -> BudgetPeriod | None:
        stmt = (
            select(BudgetPeriod)
            .where(BudgetPeriod.id == period_id)
            .options(joinedload(BudgetPeriod.lines))
        )
        return self._session.execute(stmt).scalar_one_or_none()

    # --- Lines ---

    def get_line(self, line_id: int) -> BudgetLine | None:
        return self._session.get(BudgetLine, line_id)

    def get_lines_by_period(self, period_id: int) -> list[BudgetLine]:
        stmt = (
            select(BudgetLine)
            .where(BudgetLine.period_id == period_id)
            .order_by(BudgetLine.sort_order, BudgetLine.id)
        )
        return list(self._session.execute(stmt).scalars().all())

    def add_line(self, line: BudgetLine) -> None:
        self._session.add(line)

    def delete_line(self, line_id: int) -> None:
        line = self.get_line(line_id)
        if line:
            # Also delete children
            children = self._session.execute(
                select(BudgetLine).where(BudgetLine.parent_id == line_id)
            ).scalars().all()
            for child in children:
                self._session.delete(child)
            self._session.delete(line)

    def update_line_planned(self, line_id: int, planned_amount: Decimal) -> None:
        self._session.execute(
            update(BudgetLine)
            .where(BudgetLine.id == line_id)
            .values(planned_amount=planned_amount)
        )

    def get_root_lines(self, period_id: int) -> list[BudgetLine]:
        stmt = (
            select(BudgetLine)
            .where(
                BudgetLine.period_id == period_id,
                BudgetLine.parent_id.is_(None),
            )
            .order_by(BudgetLine.sort_order, BudgetLine.id)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_children(self, parent_id: int) -> list[BudgetLine]:
        stmt = (
            select(BudgetLine)
            .where(BudgetLine.parent_id == parent_id)
            .order_by(BudgetLine.sort_order, BudgetLine.id)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_total_planned(self, period_id: int, budget_type: str) -> Decimal:
        """Sum of planned amounts for leaf nodes of a given type in the period."""
        stmt = (
            select(func.coalesce(func.sum(BudgetLine.planned_amount), 0))
            .where(
                BudgetLine.period_id == period_id,
                BudgetLine.budget_type == budget_type,
                BudgetLine.is_group == False,  # noqa: E712
            )
        )
        result = self._session.execute(stmt).scalar()
        return result if result is not None else Decimal("0")
