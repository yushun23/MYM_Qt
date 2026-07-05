"""InvestmentService – lifecycle management for investment module."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentSettlement,
    InvestmentTrade,
    QuoteSnapshot,
    Security,
)
from mym.domain.entities.audit import AuditLog
from mym.domain.entities.import_ import ImportJob
from mym.domain.enums import (
    AccountType,
    CashFlowType,
    ImportStatus,
    InvestmentModuleStatus,
    TransactionSource,
)
from mym.infrastructure.repositories.investment_repo import InvestmentRepository

logger = logging.getLogger(__name__)


@dataclass
class InvestmentOperationResult:
    """Result of an investment operation."""
    success: bool
    entity_id: int | None = None
    affected_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class InvestmentService:
    """Service for investment module lifecycle and operations."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = InvestmentRepository(session)

    # --- InvestmentAccount Lifecycle ---

    def create_account(
        self, name: str, linked_account_id: int, broker: str | None = None,
        currency: str = "CNY", initial_capital: Decimal = Decimal("0"),
    ) -> InvestmentOperationResult:
        """Create a new investment account linked to a core Account."""
        from mym.domain.entities.account import Account

        core_acct = self._session.get(Account, linked_account_id)
        if not core_acct:
            return InvestmentOperationResult(
                success=False, errors=["关联的核心账户不存在"],
            )
        if core_acct.account_type != AccountType.INVESTMENT_LINKED:
            return InvestmentOperationResult(
                success=False,
                errors=["关联账户必须是 investment_linked 类型"],
            )

        acct = InvestmentAccount(
            name=name,
            linked_account_id=linked_account_id,
            broker=broker,
            currency=currency,
            initial_capital=initial_capital,
            module_status=InvestmentModuleStatus.ENABLED,
        )
        self._repo.add_account(acct)
        self._session.flush()

        # Record initial capital as cash flow
        if initial_capital > 0:
            cf = InvestmentCashFlow(
                investment_account_id=acct.id,
                flow_date=datetime.utcnow().date(),
                flow_type=CashFlowType.INITIAL,
                amount=initial_capital,
                notes="初始资金",
            )
            self._repo.add_cash_flow(cf)

        self._write_audit(
            "investment_account_created",
            "InvestmentAccount", str(acct.id),
            summary=f"创建: {name}, 初始资金: {initial_capital}",
        )
        logger.info("Investment account created: %s (linked to core %d)", name, linked_account_id)
        return InvestmentOperationResult(success=True, entity_id=acct.id)

    def hide_account(self, account_id: int) -> InvestmentOperationResult:
        """Hide an investment account without deleting data."""
        acct = self._repo.get_account(account_id)
        if not acct:
            return InvestmentOperationResult(
                success=False, errors=["投资账户不存在"],
            )
        self._repo.update_status(account_id, InvestmentModuleStatus.HIDDEN)
        self._write_audit(
            "investment_account_hidden",
            "InvestmentAccount", str(account_id),
            summary=f"隐藏: {acct.name}",
        )
        return InvestmentOperationResult(success=True, entity_id=account_id)

    def show_account(self, account_id: int) -> InvestmentOperationResult:
        """Show a previously hidden investment account."""
        acct = self._repo.get_account(account_id)
        if not acct:
            return InvestmentOperationResult(
                success=False, errors=["投资账户不存在"],
            )
        self._repo.update_status(account_id, InvestmentModuleStatus.ENABLED)
        self._write_audit(
            "investment_account_shown",
            "InvestmentAccount", str(account_id),
            summary=f"显示: {acct.name}",
        )
        return InvestmentOperationResult(success=True, entity_id=account_id)

    def archive_account(self, account_id: int) -> InvestmentOperationResult:
        """Archive an investment account – data preserved but excluded from reports."""
        acct = self._repo.get_account(account_id)
        if not acct:
            return InvestmentOperationResult(
                success=False, errors=["投资账户不存在"],
            )
        acct.is_archived = True
        self._repo.update_status(account_id, InvestmentModuleStatus.ARCHIVED)
        self._write_audit(
            "investment_account_archived",
            "InvestmentAccount", str(account_id),
            summary=f"归档: {acct.name}",
        )
        return InvestmentOperationResult(success=True, entity_id=account_id)

    # --- Rollback by ImportJob ---

    def rollback_import(self, import_job_id: int) -> InvestmentOperationResult:
        """Roll back all investment data imported by a specific ImportJob.

        Deletes InvestmentTrades and InvestmentCashFlows by import_job_id.
        Does NOT affect core accounting.
        """
        trades_deleted = self._repo.delete_trades_by_import(import_job_id)
        cfs_deleted = self._repo.delete_cash_flows_by_import(import_job_id)

        self._write_audit(
            "investment_import_rollback",
            "ImportJob", str(import_job_id),
            summary=f"回滚: {trades_deleted} 笔交易, {cfs_deleted} 笔资金流",
        )
        logger.info(
            "Rolled back import %d: %d trades, %d cash flows",
            import_job_id, trades_deleted, cfs_deleted,
        )
        return InvestmentOperationResult(
            success=True,
            affected_count=trades_deleted + cfs_deleted,
        )

    def permanent_delete_with_confirmation(
        self, account_id: int, backup_exists: bool, confirmed: bool
    ) -> InvestmentOperationResult:
        """Permanently delete an investment account and all associated data.

        Requires: backup_exists=True, confirmed=True (user typed confirmation).
        """
        if not backup_exists:
            return InvestmentOperationResult(
                success=False,
                errors=["必须先导出备份才能永久删除"],
            )
        if not confirmed:
            return InvestmentOperationResult(
                success=False,
                errors=["必须确认删除操作"],
            )

        acct = self._repo.get_account(account_id)
        if not acct:
            return InvestmentOperationResult(
                success=False, errors=["投资账户不存在"],
            )

        name = acct.name
        self._write_audit(
            "investment_permanent_delete",
            "InvestmentAccount", str(account_id),
            summary=f"永久删除: {name} (已备份，已确认)",
        )
        self._repo.delete_account(account_id)
        logger.warning("Permanently deleted investment account: %s", name)
        return InvestmentOperationResult(
            success=True, entity_id=account_id,
            warnings=["投资数据已永久删除"],
        )

    # --- Security ---

    def ensure_security(
        self, symbol: str, name: str, market: str = "CN",
        security_type: str = "stock",
    ) -> Security:
        """Get or create a security record."""
        sec = self._repo.find_security_by_symbol(symbol)
        if not sec:
            sec = Security(
                symbol=symbol, name=name, market=market,
                security_type=security_type,
            )
            self._repo.add_security(sec)
            self._session.flush()
        return sec

    # --- Audit ---

    def _write_audit(
        self, action: str, entity_type: str, entity_id: str,
        summary: str = "",
    ) -> None:
        audit = AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary_after=summary,
            source=TransactionSource.SYSTEM,
        )
        self._session.add(audit)
