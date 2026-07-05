"""ReceivableService – business logic for accounts receivable operations.

All receivable writes go through the core CreateTransactionUseCase (P5)
to maintain auditability and balance consistency.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.use_cases.create_transaction import (
    CreateTransactionResult,
    CreateTransactionUseCase,
)
from mym.domain.entities.receivable import ReceivableCase, ReceivableEvent
from mym.domain.enums import AccountType, ReceivableStatus, TransactionSource
from mym.infrastructure.repositories.account_repo import AccountRepository
from mym.infrastructure.repositories.receivable_repo import ReceivableRepository

logger = logging.getLogger(__name__)


@dataclass
class ReceivableOperationResult:
    """Result of a receivable operation."""
    success: bool
    case_id: Optional[int] = None
    event_id: Optional[int] = None
    transaction_id: Optional[int] = None
    errors: list[str] = field(default_factory=list)


class ReceivableService:
    """Service for managing receivable cases with proper accounting integration."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._rec_repo = ReceivableRepository(session)
        self._tx_use_case = CreateTransactionUseCase(session)

    def create_advance(
        self,
        account_id: int,
        debtor: str,
        amount: Decimal,
        occurrence_date: date,
        notes: str | None = None,
    ) -> ReceivableOperationResult:
        """Create a new advance/lend (垫付/借出).

        This creates a Transaction (lend type) and the ReceivableCase + ReceivableEvent.
        """
        # Validate account
        account = self._account_repo.get_by_id(account_id)
        if not account or account.account_type != AccountType.RECEIVABLE:
            return ReceivableOperationResult(
                success=False,
                errors=[f"账户 {account_id} 不是应收类型账户"],
            )

        # Find a source (asset) account – use first available asset
        asset_accounts = self._account_repo.list_by_type(AccountType.ASSET)
        if not asset_accounts:
            return ReceivableOperationResult(
                success=False,
                errors=["没有可用的资金来源账户"],
            )
        source_account = asset_accounts[0]

        # Create the core transaction
        tx_dto = CreateTransactionDTO(
            business_type="lend",
            transaction_date=occurrence_date,
            source=TransactionSource.MANUAL,
            description=f"垫付/借出 – {debtor}" + (f": {notes}" if notes else ""),
            lines=[
                TransactionLineDTO(
                    account_id=account_id,
                    role="debit",
                    signed_amount=amount,
                    memo=f"应收 – {debtor}",
                ),
                TransactionLineDTO(
                    account_id=source_account.id,
                    role="credit",
                    signed_amount=amount,
                    memo=f"支出 – {debtor}",
                ),
            ],
        )

        tx_result = self._tx_use_case.execute(tx_dto)
        if not tx_result.success:
            return ReceivableOperationResult(success=False, errors=tx_result.errors)

        # Create ReceivableCase
        case = ReceivableCase(
            account_id=account_id,
            debtor=debtor,
            total_amount=amount,
            recovered_amount=Decimal("0"),
            written_off_amount=Decimal("0"),
            status=ReceivableStatus.PENDING,
            notes=notes,
            occurrence_date=occurrence_date,
        )
        self._rec_repo.add_case(case)
        self._session.flush()

        # Create advance event
        event = ReceivableEvent(
            case_id=case.id,
            event_type="advance",
            event_date=occurrence_date,
            amount=amount,
            transaction_id=tx_result.transaction_id,
            notes=f"垫付创建 – {debtor}",
        )
        self._rec_repo.add_event(event)

        logger.info(
            "Receivable advance created: case=%d, debtor=%s, amount=%s",
            case.id, debtor, amount,
        )
        return ReceivableOperationResult(
            success=True,
            case_id=case.id,
            event_id=event.id,
            transaction_id=tx_result.transaction_id,
        )

    def recover(
        self,
        case_id: int,
        amount: Decimal,
        event_date: date,
        notes: str | None = None,
    ) -> ReceivableOperationResult:
        """Record a partial or full recovery of a receivable (收回欠款)."""
        case = self._rec_repo.get_by_id(case_id)
        if not case:
            return ReceivableOperationResult(success=False, errors=[f"应收记录 {case_id} 不存在"])
        if case.status in (ReceivableStatus.FULLY_RECOVERED, ReceivableStatus.WRITTEN_OFF):
            return ReceivableOperationResult(success=False, errors=["该应收记录已完成或已核销"])

        # Determine if this is full or partial recovery
        remaining = case.outstanding_amount
        if amount > remaining:
            return ReceivableOperationResult(
                success=False,
                errors=[f"收回金额 {amount} 超过未收余额 {remaining}"],
            )

        is_full = amount >= remaining

        # Find a target asset account
        asset_accounts = self._account_repo.list_by_type(AccountType.ASSET)
        if not asset_accounts:
            return ReceivableOperationResult(
                success=False,
                errors=["没有可用的资产账户"],
            )
        target_account = asset_accounts[0]

        # Create the core transaction (recover type)
        tx_dto = CreateTransactionDTO(
            business_type="recover",
            transaction_date=event_date,
            source=TransactionSource.MANUAL,
            description=f"收回欠款 – {case.debtor}" + (f": {notes}" if notes else ""),
            lines=[
                TransactionLineDTO(
                    account_id=target_account.id,
                    role="debit",
                    signed_amount=amount,
                    memo=f"收回 – {case.debtor}",
                ),
                TransactionLineDTO(
                    account_id=case.account_id,
                    role="credit",
                    signed_amount=amount,
                    memo=f"收回 – {case.debtor}",
                ),
            ],
        )

        tx_result = self._tx_use_case.execute(tx_dto)
        if not tx_result.success:
            return ReceivableOperationResult(success=False, errors=tx_result.errors)

        # Update case amounts
        self._rec_repo.update_case_amounts(case_id, recovered_delta=amount)

        # Create event
        event_type = "full_recovery" if is_full else "partial_recovery"
        event = ReceivableEvent(
            case_id=case_id,
            event_type=event_type,
            event_date=event_date,
            amount=amount,
            transaction_id=tx_result.transaction_id,
            notes=notes or f"收回 – {case.debtor}",
        )
        self._rec_repo.add_event(event)

        logger.info(
            "Receivable recovery: case=%d, amount=%s, type=%s",
            case_id, amount, event_type,
        )
        return ReceivableOperationResult(
            success=True,
            case_id=case_id,
            event_id=event.id,
            transaction_id=tx_result.transaction_id,
        )

    def write_off(
        self,
        case_id: int,
        amount: Decimal,
        event_date: date,
        notes: str | None = None,
    ) -> ReceivableOperationResult:
        """Write off a receivable as bad debt (折损/坏账)."""
        case = self._rec_repo.get_by_id(case_id)
        if not case:
            return ReceivableOperationResult(success=False, errors=[f"应收记录 {case_id} 不存在"])
        if case.status in (ReceivableStatus.FULLY_RECOVERED, ReceivableStatus.WRITTEN_OFF):
            return ReceivableOperationResult(success=False, errors=["该应收记录已完成或已核销"])

        remaining = case.outstanding_amount
        if amount > remaining:
            return ReceivableOperationResult(
                success=False,
                errors=[f"核销金额 {amount} 超过未收余额 {remaining}"],
            )

        # Create a balance_adjustment transaction for the write-off
        asset_accounts = self._account_repo.list_by_type(AccountType.ASSET)
        if not asset_accounts:
            return ReceivableOperationResult(success=False, errors=["没有可用的资产账户"])

        tx_dto = CreateTransactionDTO(
            business_type="balance_adjustment",
            transaction_date=event_date,
            source=TransactionSource.MANUAL,
            description=f"坏账核销 – {case.debtor}" + (f": {notes}" if notes else ""),
            lines=[
                TransactionLineDTO(
                    account_id=case.account_id,
                    role="debit",
                    signed_amount=amount,
                    memo=f"核销 – {case.debtor}",
                ),
                TransactionLineDTO(
                    account_id=case.account_id,
                    role="credit",
                    signed_amount=amount,
                    memo=f"核销 – {case.debtor}",
                ),
            ],
        )

        tx_result = self._tx_use_case.execute(tx_dto)
        if not tx_result.success:
            return ReceivableOperationResult(success=False, errors=tx_result.errors)

        self._rec_repo.update_case_amounts(case_id, written_off_delta=amount)

        event = ReceivableEvent(
            case_id=case_id,
            event_type="write_off",
            event_date=event_date,
            amount=amount,
            transaction_id=tx_result.transaction_id,
            notes=notes or f"坏账核销 – {case.debtor}",
        )
        self._rec_repo.add_event(event)

        logger.info(
            "Receivable write-off: case=%d, amount=%s", case_id, amount,
        )
        return ReceivableOperationResult(
            success=True,
            case_id=case_id,
            event_id=event.id,
            transaction_id=tx_result.transaction_id,
        )

    def get_unrecovered_report(self) -> list[dict]:
        """Get unrecovered receivable report."""
        cases = self._rec_repo.list_active()
        report = []
        for case in cases:
            events = self._rec_repo.get_events(case.id)
            report.append({
                "id": case.id,
                "debtor": case.debtor,
                "total": str(case.total_amount),
                "recovered": str(case.recovered_amount),
                "written_off": str(case.written_off_amount),
                "outstanding": str(case.outstanding_amount),
                "status": case.status,
                "occurrence_date": str(case.occurrence_date),
                "notes": case.notes or "",
                "event_count": len(events),
            })
        return report
