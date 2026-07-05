"""SettlementService – monthly P&L settlement into core ledger (P27)."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentSettlement,
)
from mym.domain.entities.account import Account
from mym.domain.entities.audit import AuditLog
from mym.domain.enums import (
    AccountType,
    CashFlowType,
    TransactionSource,
)
from mym.infrastructure.repositories.investment_repo import InvestmentRepository

logger = logging.getLogger(__name__)


@dataclass
class SettlementPreview:
    """Preview of a monthly settlement before generation."""
    investment_account_id: int
    year: int
    month: int
    start_total_assets: Decimal = Decimal("0")
    end_total_assets: Decimal = Decimal("0")
    net_inflow: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    dividend_income: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SettlementResult:
    success: bool
    settlement_id: int | None = None
    profit_tx_id: int | None = None
    loss_tx_id: int | None = None
    errors: list[str] = field(default_factory=list)


class SettlementService:
    """Generates monthly investment settlement records into core ledger."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = InvestmentRepository(session)
        self._tx_uc = CreateTransactionUseCase(session)

    def preview(
        self, investment_account_id: int, year: int, month: int
    ) -> SettlementPreview:
        """Compute settlement preview without writing anything."""
        acct = self._repo.get_account(investment_account_id)
        if not acct:
            return SettlementPreview(
                investment_account_id=investment_account_id,
                year=year, month=month,
                errors=["投资账户不存在"],
            )

        # Get all cash flows for the month
        from mym.application.services.stock_trading_service import StockTradingService
        trading_svc = StockTradingService(self._session)

        cfs = self._repo.list_cash_flows(account_id=investment_account_id)
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)

        month_cfs = [
            cf for cf in cfs
            if cf.flow_date >= start and cf.flow_date < end
        ]

        net_inflow = Decimal("0")
        realized_pnl = Decimal("0")
        dividend_income = Decimal("0")
        total_fees = Decimal("0")

        for cf in month_cfs:
            if cf.flow_type in (CashFlowType.TRANSFER_IN, CashFlowType.TRANSFER_OUT):
                net_inflow += cf.amount
            elif cf.flow_type in (CashFlowType.BUY, CashFlowType.SELL):
                realized_pnl += cf.amount
            elif cf.flow_type == CashFlowType.DIVIDEND:
                dividend_income += cf.amount
            elif cf.flow_type in (CashFlowType.FEE, CashFlowType.TAX):
                total_fees += cf.amount

        # Get total asset value before and after
        # For start, we need previous month end or initial capital
        start_value = acct.initial_capital
        pre_cfs = [cf for cf in cfs if cf.flow_date < start]
        start_value += sum(cf.amount for cf in pre_cfs)

        end_value = start_value + sum(cf.amount for cf in month_cfs)
        holdings_value = trading_svc.get_total_asset_value(investment_account_id)
        total_change = holdings_value - start_value - net_inflow

        return SettlementPreview(
            investment_account_id=investment_account_id,
            year=year, month=month,
            start_total_assets=start_value,
            end_total_assets=holdings_value,
            net_inflow=net_inflow,
            realized_pnl=realized_pnl,
            dividend_income=dividend_income,
            total_fees=total_fees,
            net_profit=total_change,
        )

    def generate(
        self, investment_account_id: int, year: int, month: int
    ) -> SettlementResult:
        """Generate a monthly settlement, voiding any previous one for same period."""
        preview = self.preview(investment_account_id, year, month)
        if preview.errors:
            return SettlementResult(success=False, errors=preview.errors)

        # Check for existing settlement
        existing = self._repo.get_settlement(investment_account_id, year, month)
        if existing:
            self.void_settlement(existing.id)

        acct = self._repo.get_account(investment_account_id)
        linked_acct_id = acct.linked_account_id

        profit_tx_id = None
        loss_tx_id = None

        # Create profit/loss transactions in core ledger
        settlement = InvestmentSettlement(
            investment_account_id=investment_account_id,
            year=year, month=month,
            start_total_assets=preview.start_total_assets,
            end_total_assets=preview.end_total_assets,
            net_inflow=preview.net_inflow,
            realized_pnl=preview.realized_pnl,
            dividend_income=preview.dividend_income,
            total_fees=preview.total_fees,
        )
        self._repo.add_settlement(settlement)
        self._session.flush()

        net_profit = preview.net_profit

        # Find income/expense categories for stock
        from mym.domain.entities.category import Category
        from mym.domain.enums import CategoryType
        from sqlalchemy import select

        income_cat = self._session.execute(
            select(Category).where(
                Category.category_type == CategoryType.INCOME,
                Category.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()

        expense_cat = self._session.execute(
            select(Category).where(
                Category.category_type == CategoryType.EXPENSE,
                Category.is_deleted == False,  # noqa: E712
            )
        ).scalars().first()

        # Find an asset account for the offset
        from mym.infrastructure.repositories.account_repo import AccountRepository
        ar = AccountRepository(self._session)
        asset_accounts = ar.list_by_type(AccountType.ASSET)
        default_asset = asset_accounts[0] if asset_accounts else None

        if net_profit > 0 and income_cat and default_asset:
            dto = CreateTransactionDTO(
                business_type="stock_profit",
                transaction_date=date(year, month, min(28, 28)),
                source=TransactionSource.SYSTEM,
                description=f"投资月结 {year}-{month:02d} 盈利",
                lines=[
                    TransactionLineDTO(
                        account_id=linked_acct_id,
                        role="debit",
                        signed_amount=net_profit,
                        category_id=income_cat.id,
                        memo=f"投资盈利 {year}-{month:02d}",
                    ),
                    TransactionLineDTO(
                        account_id=default_asset.id,
                        role="credit",
                        signed_amount=net_profit,
                        memo=f"投资盈利 {year}-{month:02d}",
                    ),
                ],
            )
            result = self._tx_uc.execute(dto)
            if result.success:
                profit_tx_id = result.transaction_id
                settlement.profit_transaction_id = profit_tx_id

        elif net_profit < 0 and expense_cat and default_asset:
            loss_amount = abs(net_profit)
            dto = CreateTransactionDTO(
                business_type="stock_loss",
                transaction_date=date(year, month, min(28, 28)),
                source=TransactionSource.SYSTEM,
                description=f"投资月结 {year}-{month:02d} 亏损",
                lines=[
                    TransactionLineDTO(
                        account_id=linked_acct_id,
                        role="debit",
                        signed_amount=loss_amount,
                        category_id=expense_cat.id,
                        memo=f"投资亏损 {year}-{month:02d}",
                    ),
                    TransactionLineDTO(
                        account_id=default_asset.id,
                        role="credit",
                        signed_amount=loss_amount,
                        memo=f"投资亏损 {year}-{month:02d}",
                    ),
                ],
            )
            result = self._tx_uc.execute(dto)
            if result.success:
                loss_tx_id = result.transaction_id
                settlement.loss_transaction_id = loss_tx_id

        self._session.flush()
        self._session.add(AuditLog(
            action="investment_settlement_generated",
            entity_type="InvestmentSettlement",
            entity_id=str(settlement.id),
            summary_after=f"月结 {year}-{month:02d} 净利润: {net_profit}",
            source=TransactionSource.SYSTEM,
        ))
        logger.info("Settlement generated: %d-%02d, net=%s", year, month, net_profit)
        return SettlementResult(
            success=True,
            settlement_id=settlement.id,
            profit_tx_id=profit_tx_id,
            loss_tx_id=loss_tx_id,
        )

    def void_settlement(self, settlement_id: int) -> SettlementResult:
        """Void a settlement and its associated core transactions."""
        stmt = self._session.query(InvestmentSettlement).filter(
            InvestmentSettlement.id == settlement_id
        )
        settlement = stmt.first()
        if not settlement:
            return SettlementResult(success=False, errors=["结算记录不存在"])

        # Void associated core transactions
        from mym.application.use_cases.void_transaction import VoidTransactionUseCase
        void_uc = VoidTransactionUseCase(self._session)

        if settlement.profit_transaction_id:
            void_uc.execute(settlement.profit_transaction_id)
        if settlement.loss_transaction_id:
            void_uc.execute(settlement.loss_transaction_id)

        self._repo.deactivate_settlement(settlement_id)
        self._session.add(AuditLog(
            action="investment_settlement_voided",
            entity_type="InvestmentSettlement",
            entity_id=str(settlement_id),
            summary_after=f"作废月结 {settlement.period_label}",
            source=TransactionSource.SYSTEM,
        ))
        return SettlementResult(success=True, settlement_id=settlement_id)

    def replace(
        self, investment_account_id: int, year: int, month: int
    ) -> SettlementResult:
        """Replace (regenerate) a monthly settlement."""
        existing = self._repo.get_settlement(investment_account_id, year, month)
        if existing:
            self.void_settlement(existing.id)
        return self.generate(investment_account_id, year, month)
