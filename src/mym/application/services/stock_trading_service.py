"""StockTradingService – trade execution, holdings, dividends, edit/delete (P23-P24)."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentTrade,
    Security,
)
from mym.domain.entities.audit import AuditLog
from mym.domain.enums import (
    CashFlowType,
    TransactionSource,
)
from mym.infrastructure.repositories.investment_repo import InvestmentRepository

logger = logging.getLogger(__name__)


@dataclass
class Holding:
    """Current holding of a security in an account."""
    security_id: int
    symbol: str
    name: str
    quantity: Decimal
    avg_cost: Decimal
    market_price: Decimal = Decimal("0")
    market_value: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    pnl_pct: Decimal = Decimal("0")


@dataclass
class TradeResult:
    success: bool
    trade_id: int | None = None
    cf_id: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StockTradingService:
    """Service for stock trading operations: buy, sell, dividend, holdings."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = InvestmentRepository(session)

    # --- Buy ---

    def buy(
        self,
        investment_account_id: int,
        security_id: int,
        trade_date: date,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
        tax: Decimal = Decimal("0"),
        notes: str | None = None,
    ) -> TradeResult:
        """Execute a buy trade."""
        acct = self._repo.get_account(investment_account_id)
        if not acct:
            return TradeResult(success=False, errors=["投资账户不存在"])

        amount = quantity * price
        net_amount = amount + fee + tax

        trade = InvestmentTrade(
            investment_account_id=investment_account_id,
            security_id=security_id,
            trade_date=trade_date,
            trade_type="buy",
            quantity=quantity,
            price=price,
            amount=amount,
            fee=fee,
            tax=tax,
            net_amount=net_amount,
            notes=notes,
        )
        self._repo.add_trade(trade)
        self._session.flush()

        # Cash flow: buy outflow
        cf = InvestmentCashFlow(
            investment_account_id=investment_account_id,
            trade_id=trade.id,
            flow_date=trade_date,
            flow_type=CashFlowType.BUY,
            amount=-net_amount,
            notes=f"买入 {quantity}股 @ {price}",
        )
        self._repo.add_cash_flow(cf)

        self._audit("stock_buy", "InvestmentTrade", str(trade.id), f"买入: {quantity}股")
        logger.info("Buy: acct=%d, sec=%d, qty=%s, price=%s", investment_account_id, security_id, quantity, price)
        return TradeResult(success=True, trade_id=trade.id, cf_id=cf.id)

    # --- Sell ---

    def sell(
        self,
        investment_account_id: int,
        security_id: int,
        trade_date: date,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
        tax: Decimal = Decimal("0"),
        notes: str | None = None,
    ) -> TradeResult:
        """Execute a sell trade."""
        # Check holdings
        holdings = self.get_holdings(investment_account_id)
        h = next((h for h in holdings if h.security_id == security_id), None)
        if not h or h.quantity < quantity:
            return TradeResult(
                success=False,
                errors=[f"持仓不足: 需要 {quantity}, 持有 {h.quantity if h else 0}"],
            )

        amount = quantity * price
        net_amount = amount - fee - tax

        trade = InvestmentTrade(
            investment_account_id=investment_account_id,
            security_id=security_id,
            trade_date=trade_date,
            trade_type="sell",
            quantity=quantity,
            price=price,
            amount=amount,
            fee=fee,
            tax=tax,
            net_amount=net_amount,
            notes=notes,
        )
        self._repo.add_trade(trade)
        self._session.flush()

        cf = InvestmentCashFlow(
            investment_account_id=investment_account_id,
            trade_id=trade.id,
            flow_date=trade_date,
            flow_type=CashFlowType.SELL,
            amount=net_amount,
            notes=f"卖出 {quantity}股 @ {price}",
        )
        self._repo.add_cash_flow(cf)

        self._audit("stock_sell", "InvestmentTrade", str(trade.id), f"卖出: {quantity}股")
        return TradeResult(success=True, trade_id=trade.id, cf_id=cf.id)

    # --- Dividend ---

    def record_dividend(
        self,
        investment_account_id: int,
        security_id: int,
        flow_date: date,
        amount: Decimal,
        notes: str | None = None,
    ) -> TradeResult:
        """Record a dividend payment."""
        acct = self._repo.get_account(investment_account_id)
        if not acct:
            return TradeResult(success=False, errors=["投资账户不存在"])

        cf = InvestmentCashFlow(
            investment_account_id=investment_account_id,
            flow_date=flow_date,
            flow_type=CashFlowType.DIVIDEND,
            amount=amount,
            notes=notes or "股息",
        )
        self._repo.add_cash_flow(cf)
        self._session.flush()
        self._audit("stock_dividend", "InvestmentCashFlow", str(cf.id), f"股息: {amount}")
        return TradeResult(success=True, cf_id=cf.id)

    # --- Transfer ---

    def transfer(
        self,
        investment_account_id: int,
        flow_date: date,
        amount: Decimal,
        flow_type: CashFlowType,
        notes: str | None = None,
    ) -> TradeResult:
        """Record a transfer in/out of the investment account."""
        if flow_type not in (CashFlowType.TRANSFER_IN, CashFlowType.TRANSFER_OUT):
            return TradeResult(success=False, errors=[f"无效的资金流类型: {flow_type}"])

        signed_amount = amount if flow_type == CashFlowType.TRANSFER_IN else -amount
        cf = InvestmentCashFlow(
            investment_account_id=investment_account_id,
            flow_date=flow_date,
            flow_type=flow_type,
            amount=signed_amount,
            notes=notes or ("银证转入" if flow_type == CashFlowType.TRANSFER_IN else "银证转出"),
        )
        self._repo.add_cash_flow(cf)
        self._session.flush()
        self._audit("stock_transfer", "InvestmentCashFlow", str(cf.id), f"{flow_type}: {amount}")
        return TradeResult(success=True, cf_id=cf.id)

    # --- Delete / Edit Trade ---

    def delete_trade(self, trade_id: int) -> TradeResult:
        """Delete a trade and its associated cash flow."""
        trade = self._repo.get_trade(trade_id)
        if not trade:
            return TradeResult(success=False, errors=["交易记录不存在"])

        # Delete associated cash flows
        cfs = self._repo.list_cash_flows(account_id=trade.investment_account_id)
        for cf in cfs:
            if cf.trade_id == trade_id:
                self._session.delete(cf)

        self._session.delete(trade)
        self._session.flush()
        self._audit("stock_trade_deleted", "InvestmentTrade", str(trade_id), "删除交易")
        return TradeResult(success=True)

    def update_trade(
        self,
        trade_id: int,
        price: Decimal | None = None,
        quantity: Decimal | None = None,
        fee: Decimal | None = None,
        tax: Decimal | None = None,
        notes: str | None = None,
    ) -> TradeResult:
        """Update trade fields and recalculate amounts."""
        trade = self._repo.get_trade(trade_id)
        if not trade:
            return TradeResult(success=False, errors=["交易记录不存在"])

        if price is not None:
            trade.price = price
        if quantity is not None:
            trade.quantity = quantity
        if fee is not None:
            trade.fee = fee
        if tax is not None:
            trade.tax = tax
        if notes is not None:
            trade.notes = notes

        # Recalculate
        trade.amount = trade.quantity * trade.price
        if trade.trade_type == "buy":
            trade.net_amount = trade.amount + trade.fee + trade.tax
        else:
            trade.net_amount = trade.amount - trade.fee - trade.tax

        self._session.flush()
        return TradeResult(success=True, trade_id=trade_id)

    # --- Holdings ---

    def get_holdings(
        self, investment_account_id: int
    ) -> list[Holding]:
        """Calculate current holdings for an investment account."""
        trades = self._repo.list_trades(account_id=investment_account_id)

        # Group by security
        by_sec: dict[int, dict] = {}
        for t in trades:
            if t.security_id not in by_sec:
                sec = self._repo.get_security(t.security_id)
                by_sec[t.security_id] = {
                    "symbol": sec.symbol if sec else "?",
                    "name": sec.name if sec else "?",
                    "quantity": Decimal("0"),
                    "total_cost": Decimal("0"),
                }
            if t.trade_type == "buy":
                by_sec[t.security_id]["quantity"] += t.quantity
                by_sec[t.security_id]["total_cost"] += t.net_amount
            elif t.trade_type == "sell":
                by_sec[t.security_id]["quantity"] -= t.quantity
                # Reduce cost proportionally
                if by_sec[t.security_id]["quantity"] > 0:
                    ratio = t.quantity / (by_sec[t.security_id]["quantity"] + t.quantity)
                    by_sec[t.security_id]["total_cost"] -= (
                        by_sec[t.security_id]["total_cost"] * ratio
                    )

        holdings = []
        for sec_id, data in by_sec.items():
            if data["quantity"] <= 0:
                continue
            avg_cost = data["total_cost"] / data["quantity"] if data["quantity"] > 0 else Decimal("0")
            # Try to get latest quote
            quote = self._repo.get_latest_quote(sec_id)
            market_price = quote.close_price if quote else Decimal("0")
            market_value = data["quantity"] * market_price
            unrealized = market_value - data["total_cost"]
            pnl_pct = (unrealized / data["total_cost"] * 100) if data["total_cost"] > 0 else Decimal("0")

            holdings.append(Holding(
                security_id=sec_id,
                symbol=data["symbol"],
                name=data["name"],
                quantity=data["quantity"],
                avg_cost=avg_cost,
                market_price=market_price,
                market_value=market_value,
                unrealized_pnl=unrealized,
                pnl_pct=round(pnl_pct, 2),
            ))
        return holdings

    def get_total_asset_value(self, investment_account_id: int) -> Decimal:
        """Get total market value of holdings + cash balance."""
        holdings = self.get_holdings(investment_account_id)
        market_value = sum(h.market_value for h in holdings)

        # Get cash balance from cash flows
        cfs = self._repo.list_cash_flows(account_id=investment_account_id)
        cash = sum(cf.amount for cf in cfs)

        return market_value + cash

    # --- Audit ---

    def _audit(self, action: str, entity_type: str, entity_id: str, summary: str) -> None:
        self._session.add(AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary_after=summary,
            source=TransactionSource.SYSTEM,
        ))
