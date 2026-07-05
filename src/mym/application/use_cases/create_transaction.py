"""CreateTransactionUseCase – unified write entry for all business types."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import CreateTransactionDTO
from mym.application.use_cases.validate_transaction import (
    ValidateTransactionUseCase,
)
from mym.domain.entities.audit import AuditLog
from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import AccountType, TransactionRole, TransactionSource, TransactionStatus
from mym.infrastructure.repositories.account_repo import AccountRepository
from mym.infrastructure.repositories.audit_repo import AuditLogRepository
from mym.infrastructure.repositories.category_repo import CategoryRepository
from mym.infrastructure.repositories.transaction_repo import TransactionRepository

logger = logging.getLogger(__name__)


@dataclass
class CreateTransactionResult:
    """Result of creating a transaction."""

    success: bool
    transaction_id: Optional[int] = None
    errors: list[str] = field(default_factory=list)


class CreateTransactionUseCase:
    """Creates a transaction and updates account balances in one database transaction.

    Convention: ALL signed_amount values are positive.
    Balance effect:
      - DEBIT asset/receivable: +amount (increase)
      - DEBIT liability: -amount (decrease)
      - CREDIT asset/receivable: -amount (decrease)
      - CREDIT liability: +amount (increase)
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._category_repo = CategoryRepository(session)
        self._tx_repo = TransactionRepository(session)
        self._audit_repo = AuditLogRepository(session)
        self._validator = ValidateTransactionUseCase(
            self._account_repo, self._category_repo
        )

    def execute(self, dto: CreateTransactionDTO) -> CreateTransactionResult:
        """Create a transaction. All or nothing in one DB transaction."""
        validation = self._validator.execute(dto)
        if not validation.is_valid:
            return CreateTransactionResult(success=False, errors=validation.errors)

        try:
            # Create Transaction entity
            tx = Transaction(
                business_type=dto.business_type,
                transaction_date=dto.transaction_date,
                description=dto.description,
                source=TransactionSource(dto.source),
                status=TransactionStatus.POSTED,
            )

            # Create TransactionLine entities
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

            self._tx_repo.add(tx)

            # Update account balances
            self._apply_balances(tx)

            # Write audit log
            self._audit_repo.add(
                AuditLog(
                    action="create",
                    entity_type="Transaction",
                    summary_after=f"type={dto.business_type}, date={dto.transaction_date}, lines={len(dto.lines)}",
                    source=dto.source,
                )
            )

            self._session.flush()
            logger.info(
                "Transaction created: id=%d, type=%s, date=%s",
                tx.id, dto.business_type, dto.transaction_date,
            )
            return CreateTransactionResult(success=True, transaction_id=tx.id)

        except Exception as e:
            logger.exception("Failed to create transaction: %s", e)
            return CreateTransactionResult(success=False, errors=[f"创建交易失败: {e}"])

    def _apply_balances(self, tx: Transaction) -> None:
        """Apply balance effects for all lines in the transaction."""
        for line in tx.lines:
            account = self._account_repo.get_by_id(line.account_id)
            if account is None:
                continue

            delta = self._compute_delta(line.role, line.signed_amount, account.account_type)
            self._account_repo.update_balance(line.account_id, delta)

    def _compute_delta(
        self,
        role: TransactionRole,
        amount: Decimal,
        account_type: AccountType,
    ) -> Decimal:
        """Compute the balance delta for a transaction line."""
        if role == TransactionRole.DEBIT:
            if account_type == AccountType.LIABILITY:
                return -amount  # Debit reduces liability
            return amount  # Debit increases asset/receivable/investment_linked
        else:  # CREDIT
            if account_type == AccountType.LIABILITY:
                return amount  # Credit increases liability
            return -amount  # Credit reduces asset/receivable/investment_linked

    def _reverse_balances(self, tx: Transaction) -> None:
        """Reverse the balance effects of all lines."""
        for line in tx.lines:
            account = self._account_repo.get_by_id(line.account_id)
            if account is None:
                continue
            delta = self._compute_delta(line.role, line.signed_amount, account.account_type)
            self._account_repo.update_balance(line.account_id, -delta)
