"""RebuildAccountBalancesUseCase – recalculate all account balances from scratch."""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.domain.enums import TransactionStatus
from mym.infrastructure.repositories.account_repo import AccountRepository
from mym.infrastructure.repositories.transaction_repo import TransactionRepository

logger = logging.getLogger(__name__)


@dataclass
class RebuildResult:
    success: bool
    accounts_checked: int = 0
    accounts_fixed: int = 0
    errors: list[str] = field(default_factory=list)


class RebuildAccountBalancesUseCase:
    """Recalculates current_balance from opening_balance + posted transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._account_repo = AccountRepository(session)
        self._tx_repo = TransactionRepository(session)
        self._create_uc = CreateTransactionUseCase(session)

    def execute(self) -> RebuildResult:
        result = RebuildResult(success=True)

        try:
            accounts = self._account_repo.get_all()
            result.accounts_checked = len(accounts)

            for account in accounts:
                expected = account.opening_balance

                lines = self._tx_repo.get_lines_by_account(account.id)
                for line in lines:
                    if line.transaction.status != TransactionStatus.POSTED:
                        continue
                    delta = self._create_uc._compute_delta(
                        line.role, line.signed_amount, account.account_type
                    )
                    expected += delta

                if expected != account.current_balance:
                    self._account_repo.set_balance(account.id, expected)
                    result.accounts_fixed += 1
                    logger.info(
                        "Fixed balance: account=%s(%d) old=%s new=%s",
                        account.name, account.id, account.current_balance, expected,
                    )

            self._session.flush()
            logger.info("Rebalance: %d checked, %d fixed", result.accounts_checked, result.accounts_fixed)

        except Exception as e:
            logger.exception("Rebalance failed: %s", e)
            result.success = False
            result.errors.append(str(e))

        return result
