"""Receivable repository."""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mym.domain.entities.receivable import ReceivableCase, ReceivableEvent
from mym.domain.enums import ReceivableStatus


class ReceivableRepository:
    """Repository for ReceivableCase and ReceivableEvent entities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, case_id: int) -> ReceivableCase | None:
        return self._session.get(ReceivableCase, case_id)

    def list_all(self, status: ReceivableStatus | None = None) -> list[ReceivableCase]:
        """List all receivable cases, optionally filtered by status."""
        stmt = select(ReceivableCase).where(
            ReceivableCase.is_deleted == False  # noqa: E712
        )
        if status:
            stmt = stmt.where(ReceivableCase.status == status)
        stmt = stmt.order_by(ReceivableCase.occurrence_date.desc())
        return list(self._session.execute(stmt).scalars().all())

    def list_by_account(self, account_id: int) -> list[ReceivableCase]:
        """List cases for a specific receivable account."""
        stmt = (
            select(ReceivableCase)
            .where(
                ReceivableCase.account_id == account_id,
                ReceivableCase.is_deleted == False,  # noqa: E712
            )
            .order_by(ReceivableCase.occurrence_date.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_by_debtor(self, debtor: str) -> list[ReceivableCase]:
        """List cases for a specific debtor."""
        stmt = (
            select(ReceivableCase)
            .where(
                ReceivableCase.debtor == debtor,
                ReceivableCase.is_deleted == False,  # noqa: E712
            )
            .order_by(ReceivableCase.occurrence_date.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def list_active(self) -> list[ReceivableCase]:
        """List cases that are not fully recovered or written off."""
        return self.list_pending() + self.list_partially_recovered()

    def list_pending(self) -> list[ReceivableCase]:
        """List cases with status PENDING."""
        return self.list_all(status=ReceivableStatus.PENDING)

    def list_partially_recovered(self) -> list[ReceivableCase]:
        """List cases with status PARTIALLY_RECOVERED."""
        return self.list_all(status=ReceivableStatus.PARTIALLY_RECOVERED)

    def add_case(self, case: ReceivableCase) -> None:
        self._session.add(case)

    def add_event(self, event: ReceivableEvent) -> None:
        self._session.add(event)

    def update_case_status(self, case_id: int, status: ReceivableStatus) -> None:
        self._session.execute(
            update(ReceivableCase)
            .where(ReceivableCase.id == case_id)
            .values(status=status)
        )

    def update_case_amounts(
        self,
        case_id: int,
        recovered_delta: Decimal = Decimal("0"),
        written_off_delta: Decimal = Decimal("0"),
    ) -> None:
        """Atomically increment recovered/written_off amounts."""
        case = self.get_by_id(case_id)
        if case:
            case.recovered_amount += recovered_delta
            case.written_off_amount += written_off_delta
            # Update status based on new amounts
            if case.recovered_amount + case.written_off_amount >= case.total_amount:
                if case.written_off_amount > 0:
                    case.status = ReceivableStatus.WRITTEN_OFF
                else:
                    case.status = ReceivableStatus.FULLY_RECOVERED
            elif case.recovered_amount > 0:
                case.status = ReceivableStatus.PARTIALLY_RECOVERED

    def get_events(self, case_id: int) -> list[ReceivableEvent]:
        """Get all events for a case, ordered by date."""
        stmt = (
            select(ReceivableEvent)
            .where(ReceivableEvent.case_id == case_id)
            .order_by(ReceivableEvent.event_date)
        )
        return list(self._session.execute(stmt).scalars().all())

    def get_total_outstanding_by_account(self, account_id: int) -> Decimal:
        """Get total outstanding amount for a receivable account."""
        cases = self.list_by_account(account_id)
        return sum(c.outstanding_amount for c in cases)

    def get_total_outstanding(self) -> Decimal:
        """Get total outstanding amount across all accounts."""
        cases = self.list_all()
        return sum(c.outstanding_amount for c in cases if c.status not in (
            ReceivableStatus.FULLY_RECOVERED, ReceivableStatus.WRITTEN_OFF
        ))
