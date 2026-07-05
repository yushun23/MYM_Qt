"""Investment domain entities – stocks, trades, cash flows, quotes, settlements."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mym.domain.enums import CashFlowType, InvestmentModuleStatus
from mym.infrastructure.database.base import (
    ArchivableMixin,
    Base,
    IntegerPrimaryKeyMixin,
    TimestampMixin,
)
from mym.infrastructure.database.types_ import Money


class InvestmentAccount(Base, IntegerPrimaryKeyMixin, TimestampMixin, ArchivableMixin):
    """An investment/brokerage account linked to a core Account."""

    __tablename__ = "investment_accounts"
    __table_args__ = (
        CheckConstraint(
            "module_status IN ('enabled','hidden','archived')",
            name="ck_inv_acct_status",
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    linked_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False
    )
    broker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    module_status: Mapped[InvestmentModuleStatus] = mapped_column(
        String(20), default=InvestmentModuleStatus.ENABLED, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reverse ref
    linked_account: Mapped["Account"] = relationship("Account", lazy="selectin")

    trades: Mapped[list["InvestmentTrade"]] = relationship(
        "InvestmentTrade", back_populates="investment_account",
        cascade="all, delete-orphan", lazy="selectin",
    )
    cash_flows: Mapped[list["InvestmentCashFlow"]] = relationship(
        "InvestmentCashFlow", back_populates="investment_account",
        cascade="all, delete-orphan", lazy="selectin",
    )

    @property
    def is_hidden(self) -> bool:
        return self.module_status == InvestmentModuleStatus.HIDDEN

    def __repr__(self) -> str:
        return f"<InvestmentAccount(id={self.id}, name='{self.name}')>"


class Security(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Master data for a security (stock, ETF, bond, etc.)."""

    __tablename__ = "securities"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(10), nullable=False, default="CN")
    security_type: Mapped[str] = mapped_column(String(20), default="stock", nullable=False)
    industry: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_listed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    quotes: Mapped[list["QuoteSnapshot"]] = relationship(
        "QuoteSnapshot", back_populates="security",
        cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Security(id={self.id}, symbol='{self.symbol}', name='{self.name}')>"


class InvestmentTrade(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """A trade record: buy or sell of a security."""

    __tablename__ = "investment_trades"
    __table_args__ = (
        CheckConstraint(
            "trade_type IN ('buy','sell')",
            name="ck_trade_type",
        ),
    )

    investment_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("investment_accounts.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("securities.id"), nullable=False
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    trade_type: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Money, nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    tax: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    import_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_jobs.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    investment_account: Mapped["InvestmentAccount"] = relationship(
        "InvestmentAccount", back_populates="trades"
    )
    security: Mapped["Security"] = relationship("Security", lazy="selectin")

    @property
    def is_buy(self) -> bool:
        return self.trade_type == "buy"

    def __repr__(self) -> str:
        return (
            f"<InvestmentTrade(id={self.id}, {self.trade_type}, "
            f"{self.quantity}@{self.price})>"
        )


class InvestmentCashFlow(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Cash flow record: transfer in/out, dividend, fee, tax, adjustment."""

    __tablename__ = "investment_cash_flows"
    __table_args__ = (
        CheckConstraint(
            "flow_type IN ('initial','transfer_in','transfer_out','adjustment',"
            "'buy','sell','dividend','fee','tax')",
            name="ck_cashflow_type",
        ),
    )

    investment_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("investment_accounts.id", ondelete="CASCADE"), nullable=False
    )
    trade_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("investment_trades.id"), nullable=True
    )
    flow_date: Mapped[date] = mapped_column(Date, nullable=False)
    flow_type: Mapped[CashFlowType] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    import_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_jobs.id"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    investment_account: Mapped["InvestmentAccount"] = relationship(
        "InvestmentAccount", back_populates="cash_flows"
    )

    @property
    def is_inflow(self) -> bool:
        return self.flow_type in (
            CashFlowType.TRANSFER_IN,
            CashFlowType.DIVIDEND,
            CashFlowType.SELL,
        )

    def __repr__(self) -> str:
        return (
            f"<InvestmentCashFlow(id={self.id}, type={self.flow_type}, "
            f"amount={self.amount})>"
        )


class QuoteSnapshot(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Price snapshot for a security at a point in time."""

    __tablename__ = "quote_snapshots"

    security_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("securities.id"), nullable=False
    )
    quote_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    high_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    low_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    close_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    security: Mapped["Security"] = relationship("Security", back_populates="quotes")

    def __repr__(self) -> str:
        return (
            f"<QuoteSnapshot(id={self.id}, symbol='{self.security.symbol if self.security else '?'}', "
            f"date={self.quote_date}, close={self.close_price})>"
        )


class InvestmentSettlement(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    """Monthly settlement record – results synced to core ledger."""

    __tablename__ = "investment_settlements"
    __table_args__ = (
        CheckConstraint(
            "month BETWEEN 1 AND 12", name="ck_settlement_month"
        ),
    )

    investment_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("investment_accounts.id"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    start_total_market_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    start_total_assets: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    end_total_market_value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    end_total_assets: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    net_inflow: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    dividend_income: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    total_fees: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"), nullable=False)
    profit_transaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=True
    )
    loss_transaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transactions.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    investment_account: Mapped["InvestmentAccount"] = relationship("InvestmentAccount", lazy="selectin")

    @property
    def period_label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    def __repr__(self) -> str:
        return (
            f"<InvestmentSettlement(id={self.id}, {self.period_label}, "
            f"pnl={self.realized_pnl})>"
        )


# Forward references
from mym.domain.entities.account import Account  # noqa: E402, F811
