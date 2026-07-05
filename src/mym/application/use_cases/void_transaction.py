"""VoidTransactionUseCase – auditably void a transaction."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from mym.domain.entities.audit import AuditLog
from mym.domain.enums import TransactionRole
from mym.infrastructure.repositories.account_repo import AccountRepository
from mym.infrastructure.repositories.audit_repo import AuditLogRepository
from mym.infrastructure.repositories.transaction_repo import TransactionRepository

logger = logging.getLogger(__name__)


@dataclass
class VoidTransactionResult:
    """Result of voiding a transaction."""

    success: bool
    errors: list[str] = field(default_factory=list)


class VoidTransactionUseCase:
    """Voids a transaction and reverses its balance effects.

    Default: audit-able void (marks as void, reverses balances).
    Physical delete only allowed in controlled import batch rollback scenarios.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._tx_repo = TransactionRepository(session)
        self._audit_repo = AuditLogRepository(session)

    def execute(self, tx_id: int) -> VoidTransactionResult:
        tx = self._tx_repo.get_by_id(tx_id)
        if tx is None:
            return VoidTransactionResult(success=False, errors=["交易不存在"])
        if tx.status.value == "void":
            return VoidTransactionResult(success=False, errors=["交易已作废"])

        try:
            # Reverse balances
            for line in tx.lines:
                delta = line.signed_amount
                if line.role == TransactionRole.DEBIT:
                    account = self._account_repo.get_by_id(line.account_id)
                    if account and account.account_type.value == "liability":
                        delta = delta
                    self._account_repo.update_balance(line.account_id, -delta)
                elif line.role == TransactionRole.CREDIT:
                    account = self._account_repo.get_by_id(line.account_id)
                    if account and account.account_type.value == "liability":
                        delta = -delta
                    self._account_repo.update_balance(line.account_id, delta)

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
            return VoidTransactionResult(success=True)

        except Exception as e:
            logger.exception("Failed to void transaction: %s", e)
            return VoidTransactionResult(success=False, errors=[f"作废失败: {e}"])
