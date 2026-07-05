"""UpdateTransactionUseCase – modify an existing transaction."""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import UpdateTransactionDTO
from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.domain.entities.audit import AuditLog
from mym.domain.entities.transaction import TransactionLine
from mym.domain.enums import AccountType, TransactionRole
from mym.infrastructure.repositories.account_repo import AccountRepository
from mym.infrastructure.repositories.audit_repo import AuditLogRepository
from mym.infrastructure.repositories.transaction_repo import TransactionRepository

logger = logging.getLogger(__name__)


@dataclass
class UpdateTransactionResult:
    success: bool
    errors: list[str] = field(default_factory=list)


class UpdateTransactionUseCase:
    """Updates a transaction, reversing old balance effects and applying new ones."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._tx_repo = TransactionRepository(session)
        self._audit_repo = AuditLogRepository(session)
        # Use the same delta computation from CreateTransactionUseCase
        self._create_uc = CreateTransactionUseCase(session)

    def execute(self, dto: UpdateTransactionDTO) -> UpdateTransactionResult:
        tx = self._tx_repo.get_by_id(dto.transaction_id)
        if tx is None:
            return UpdateTransactionResult(success=False, errors=["交易不存在"])
        if tx.status.value == "void":
            return UpdateTransactionResult(success=False, errors=["已作废的交易不可编辑"])

        old_summary = f"date={tx.transaction_date}, desc={tx.description}"

        try:
            # Reverse old balances
            self._create_uc._reverse_balances(tx)

            # Apply changes
            if dto.transaction_date is not None:
                tx.transaction_date = dto.transaction_date
            if dto.description is not None:
                tx.description = dto.description

            if dto.lines is not None:
                tx.lines.clear()
                for line_dto in dto.lines:
                    line = TransactionLine(
                        account_id=line_dto.account_id,
                        category_id=line_dto.category_id,
                        role=TransactionRole(line_dto.role),
                        signed_amount=line_dto.signed_amount,
                        memo=line_dto.memo,
                        sort_order=line_dto.sort_order,
                    )
                    tx.lines.append(line)

            # Apply new balances
            self._create_uc._apply_balances(tx)

            # Audit
            self._audit_repo.add(
                AuditLog(
                    action="update",
                    entity_type="Transaction",
                    entity_id=str(tx.id),
                    summary_before=old_summary,
                    summary_after=f"date={tx.transaction_date}, desc={tx.description}",
                    source="manual",
                )
            )

            self._session.flush()
            logger.info("Transaction updated: id=%d", tx.id)
            return UpdateTransactionResult(success=True)

        except Exception as e:
            logger.exception("Failed to update transaction: %s", e)
            return UpdateTransactionResult(success=False, errors=[f"更新失败: {e}"])


class VoidTransactionUseCase:
    """Voids a transaction and reverses its balance effects."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._tx_repo = TransactionRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._create_uc = CreateTransactionUseCase(session)

    def execute(self, tx_id: int) -> UpdateTransactionResult:
        tx = self._tx_repo.get_by_id(tx_id)
        if tx is None:
            return UpdateTransactionResult(success=False, errors=["交易不存在"])
        if tx.status.value == "void":
            return UpdateTransactionResult(success=False, errors=["交易已作废"])

        try:
            # Reverse balances
            self._create_uc._reverse_balances(tx)

            # Mark void
            self._tx_repo.void(tx_id)

            # Audit
            self._audit_repo.add(
                AuditLog(
                    action="void",
                    entity_type="Transaction",
                    entity_id=str(tx_id),
                    summary_before=f"type={tx.business_type}, date={tx.transaction_date}",
                    source="manual",
                )
            )

            self._session.flush()
            logger.info("Transaction voided: id=%d", tx_id)
            return UpdateTransactionResult(success=True)

        except Exception as e:
            logger.exception("Failed to void transaction: %s", e)
            return UpdateTransactionResult(success=False, errors=[f"作废失败: {e}"])
