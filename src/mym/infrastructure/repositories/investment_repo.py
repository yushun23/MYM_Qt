"""Investment repository – persistence for investment domain entities."""

from datetime import date
from decimal import Decimal

from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentTrade,
    Security,
)
from mym.domain.enums import InvestmentModuleStatus


class InvestmentRepository:
    """Repository for all investment-related persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- InvestmentAccount ---

    def get_account(self, account_id: int) -> InvestmentAccount | None:
        return self._session.get(InvestmentAccount, account_id)

    def list_accounts(
        self, status: InvestmentModuleStatus | None = None
    ) -> list[InvestmentAccount]:
        stmt = select(InvestmentAccount)
        if status:
            stmt = stmt.where(InvestmentAccount.module_status == status)
        return list(self._session.execute(stmt).scalars().all())

    def list_visible_accounts(self) -> list[InvestmentAccount]:
        return self.list_accounts(InvestmentModuleStatus.ENABLED)

    def list_with_status(self) -> list[InvestmentAccount]:
        return list(
            self._session.execute(
                select(InvestmentAccount)
            ).scalars().all()
        )

    def add_account(self, account: InvestmentAccount) -> None:
        self._session.add(account)

    def update_status(
        self, account_id: int, status: InvestmentModuleStatus
    ) -> None:
        self._session.execute(
            update(InvestmentAccount)
            .where(InvestmentAccount.id == account_id)
            .values(module_status=status)
        )

    def delete_account(self, account_id: int) -> None:
        """Delete account and cascade. Requires flush to clear identity map."""
        acct = self.get_account(account_id)
        if acct:
            self._session.delete(acct)

    # --- Security ---

    def get_security(self, sec_id: int) -> Security | None:
        return self._session.get(Security, sec_id)

    def find_security_by_symbol(self, symbol: str) -> Security | None:
        stmt = select(Security).where(Security.symbol == symbol)
        return self._session.execute(stmt).scalar_one_or_none()

    def list_securities(self) -> list[Security]:
        return list(
            self._session.execute(select(Security)).scalars().all()
        )

    def add_security(self, security: Security) -> None:
        self._session.add(security)

    # --- InvestmentTrade ---

    def get_trade(self, trade_id: int) -> InvestmentTrade | None:
        return self._session.get(InvestmentTrade, trade_id)

    def list_trades(
        self, account_id: int | None = None, import_job_id: int | None = None
    ) -> list[InvestmentTrade]:
        stmt = select(InvestmentTrade)
        if account_id:
            stmt = stmt.where(InvestmentTrade.investment_account_id == account_id)
        if import_job_id:
            stmt = stmt.where(InvestmentTrade.import_job_id == import_job_id)
        stmt = stmt.order_by(InvestmentTrade.trade_date.desc())
        return list(self._session.execute(stmt).scalars().all())

    def add_trade(self, trade: InvestmentTrade) -> None:
        self._session.add(trade)

    def delete_trades_by_import(self, import_job_id: int) -> int:
        trades = self.list_trades(import_job_id=import_job_id)
        count = len(trades)
        for t in trades:
            self._session.delete(t)
        return count

    # --- InvestmentCashFlow ---

    def list_cash_flows(
        self, account_id: int | None = None, import_job_id: int | None = None
    ) -> list[InvestmentCashFlow]:
        stmt = select(InvestmentCashFlow)
        if account_id:
            stmt = stmt.where(InvestmentCashFlow.investment_account_id == account_id)
        if import_job_id:
            stmt = stmt.where(InvestmentCashFlow.import_job_id == import_job_id)
        stmt = stmt.order_by(InvestmentCashFlow.flow_date)
        return list(self._session.execute(stmt).scalars().all())

    def add_cash_flow(self, cf: InvestmentCashFlow) -> None:
        self._session.add(cf)

    def delete_cash_flows_by_import(self, import_job_id: int) -> int:
        cfs = self.list_cash_flows(import_job_id=import_job_id)
        count = len(cfs)
        for cf in cfs:
            self._session.delete(cf)
        return count

    def get_net_cash_flow(
        self, account_id: int, year: int, month: int
    ) -> Decimal:
        """Net inflow/outflow for an account in a month."""
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)

        stmt = select(func.coalesce(func.sum(InvestmentCashFlow.amount), 0)).where(
            InvestmentCashFlow.investment_account_id == account_id,
            InvestmentCashFlow.flow_date >= start,
            InvestmentCashFlow.flow_date < end,
        )
        result = self._session.execute(stmt).scalar()
        return result if result is not None else Decimal("0")

