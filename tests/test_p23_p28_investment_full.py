"""Tests for P23-P28 – Full investment module: trading, quotes, settlement, import."""

import csv
import io
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.broker_import_service import BrokerImportService
from mym.application.services.investment_service import InvestmentService
from mym.application.services.quote_service import QuoteService
from mym.application.services.settlement_service import SettlementService
from mym.application.services.stock_trading_service import (
    Holding,
    StockTradingService,
    TradeResult,
)
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentTrade,
    Security,
)
from mym.domain.enums import (
    AccountType,
    CashFlowType,
    CategoryType,
    ImportStatus,
    InvestmentModuleStatus,
)
from mym.infrastructure.database.db_manager import DatabaseManager
from mym.infrastructure.repositories.investment_repo import InvestmentRepository


@pytest.fixture
def db_mgr():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    yield mgr
    mgr.close()
    tmp_path.unlink(missing_ok=True)


@pytest.fixture
def session(db_mgr: DatabaseManager) -> Session:
    s = db_mgr.new_session()
    yield s
    s.close()


def _make_core_account(session, name, atype):
    acct = Account(name=name, account_type=atype, opening_balance=Decimal("0"), current_balance=Decimal("0"))
    session.add(acct)
    session.flush()
    return acct


def _make_category(session, name, ctype):
    cat = Category(name=name, category_type=ctype)
    session.add(cat)
    session.flush()
    return cat


def _setup_investment_account(session) -> InvestmentAccount:
    core = _make_core_account(session, "股票联动", AccountType.INVESTMENT_LINKED)
    _make_core_account(session, "现金", AccountType.ASSET)
    _make_category(session, "投资收益", CategoryType.INCOME)
    _make_category(session, "投资亏损", CategoryType.EXPENSE)
    svc = InvestmentService(session)
    result = svc.create_account("券商A", core.id, initial_capital=Decimal("100000"))
    session.flush()
    return InvestmentRepository(session).get_account(result.entity_id)


def _ensure_security(session, symbol="600519", name="贵州茅台") -> Security:
    svc = InvestmentService(session)
    return svc.ensure_security(symbol, name)


class TestStockTrading:
    def test_buy(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        result = svc.buy(
            acct.id, sec.id, date(2025, 7, 1),
            Decimal("100"), Decimal("50"),
        )
        assert result.success
        assert result.trade_id is not None

    def test_sell_insufficient(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        result = svc.sell(
            acct.id, sec.id, date(2025, 7, 1),
            Decimal("100"), Decimal("50"),
        )
        assert not result.success
        assert "持仓不足" in str(result.errors)

    def test_buy_and_sell(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        # Buy 100 shares
        r1 = svc.buy(acct.id, sec.id, date(2025, 7, 1), Decimal("100"), Decimal("50"))
        assert r1.success

        # Sell 50 shares
        r2 = svc.sell(acct.id, sec.id, date(2025, 7, 10), Decimal("50"), Decimal("60"))
        assert r2.success

        holdings = svc.get_holdings(acct.id)
        assert len(holdings) == 1
        assert holdings[0].quantity == Decimal("50")

    def test_dividend(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        result = svc.record_dividend(acct.id, sec.id, date(2025, 7, 15), Decimal("500"))
        assert result.success

    def test_transfer(self, session):
        acct = _setup_investment_account(session)
        svc = StockTradingService(session)

        result = svc.transfer(
            acct.id, date(2025, 7, 1), Decimal("10000"),
            CashFlowType.TRANSFER_IN,
        )
        assert result.success

    def test_delete_trade(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        r = svc.buy(acct.id, sec.id, date(2025, 7, 1), Decimal("100"), Decimal("50"))
        assert r.success

        r2 = svc.delete_trade(r.trade_id)
        assert r2.success

        repo = InvestmentRepository(session)
        trade = repo.get_trade(r.trade_id)
        assert trade is None

    def test_update_trade(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        r = svc.buy(acct.id, sec.id, date(2025, 7, 1), Decimal("100"), Decimal("50"))
        r2 = svc.update_trade(r.trade_id, price=Decimal("55"), fee=Decimal("10"))
        assert r2.success

        repo = InvestmentRepository(session)
        trade = repo.get_trade(r.trade_id)
        assert trade.price == Decimal("55")
        assert trade.fee == Decimal("10")

    def test_holdings_cost_basis(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)

        svc.buy(acct.id, sec.id, date(2025, 7, 1), Decimal("100"), Decimal("50"))
        session.flush()
        svc.buy(acct.id, sec.id, date(2025, 7, 5), Decimal("50"), Decimal("60"))
        session.flush()

        holdings = svc.get_holdings(acct.id)
        assert len(holdings) == 1
        assert holdings[0].quantity == Decimal("150")


class TestQuoteService:
    def test_save_and_get_quote(self, session):
        sec = _ensure_security(session)
        qs = QuoteService(session)

        qs.save_quote(sec.id, date(2025, 7, 1), Decimal("50.5"))
        session.flush()

        quote = qs.get_latest_quote(sec.id)
        assert quote is not None
        assert quote.close_price == Decimal("50.5")

    def test_is_stale(self, session):
        sec = _ensure_security(session)
        qs = QuoteService(session)

        qs.save_quote(sec.id, date(2025, 1, 1), Decimal("50"))
        session.flush()

        assert qs.is_stale(sec.id)

    def test_get_latest_price(self, session):
        sec = _ensure_security(session)
        qs = QuoteService(session)

        qs.save_quote(sec.id, date(2025, 7, 2), Decimal("55"))
        qs.save_quote(sec.id, date(2025, 7, 3), Decimal("58"))
        session.flush()

        price = qs.get_latest_price(sec.id)
        assert price == Decimal("58")


class TestSettlement:
    def test_preview(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)
        svc.buy(acct.id, sec.id, date(2025, 7, 1), Decimal("100"), Decimal("50"))
        session.flush()

        ss = SettlementService(session)
        preview = ss.preview(acct.id, 2025, 7)
        assert preview.errors == []

    def test_generate_and_void(self, session):
        acct = _setup_investment_account(session)
        sec = _ensure_security(session)
        svc = StockTradingService(session)
        svc.buy(acct.id, sec.id, date(2025, 7, 1), Decimal("100"), Decimal("50"))
        session.flush()

        ss = SettlementService(session)
        result = ss.generate(acct.id, 2025, 7)
        assert result.success
        assert result.settlement_id is not None

        # Void
        r2 = ss.void_settlement(result.settlement_id)
        assert r2.success

        repo = InvestmentRepository(session)
        stmt = repo.get_settlement(acct.id, 2025, 7)
        assert stmt is None or not stmt.is_active

    def test_preview_nonexistent_account(self, session):
        ss = SettlementService(session)
        preview = ss.preview(9999, 2025, 7)
        assert "不存在" in str(preview.errors)


class TestBrokerImport:
    def test_parse_csv(self, session):
        acct = _setup_investment_account(session)

        csv_content = (
            "日期,代码,类型,数量,价格,金额,费用\n"
            "2025-07-01,600519,买入,100,50.00,5000.00,5.00\n"
            "2025-07-05,000001,卖出,50,60.00,3000.00,3.00\n"
        )
        tmp = Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_text(csv_content)

        svc = BrokerImportService(session)
        preview = svc.parse_csv(tmp, acct.id)
        assert preview.is_ok
        assert preview.total_rows == 2
        assert preview.valid_rows == 2

        tmp.unlink()

    def test_parse_csv_errors(self, session):
        acct = _setup_investment_account(session)

        csv_content = (
            "日期,代码,类型,数量,价格\n"
            "bad-date,600519,买入,100,50.00\n"
            "2025-07-01,,买入,100,50.00\n"
        )
        tmp = Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_text(csv_content)

        svc = BrokerImportService(session)
        preview = svc.parse_csv(tmp, acct.id)
        assert not preview.is_ok
        assert len(preview.errors) > 0

        tmp.unlink()

    def test_execute_import(self, session):
        acct = _setup_investment_account(session)

        csv_content = (
            "日期,代码,类型,数量,价格,金额,费用\n"
            "2025-07-01,600519,买入,100,50.00,5000.00,5.00\n"
        )
        tmp = Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_text(csv_content)

        svc = BrokerImportService(session)
        preview = svc.parse_csv(tmp, acct.id)
        assert preview.is_ok

        result = svc.execute_import(preview, acct.id)
        assert result.success
        assert result.trades_imported == 1

        repo = InvestmentRepository(session)
        trades = repo.list_trades(account_id=acct.id)
        assert len(trades) == 1
        assert trades[0].trade_type == "buy"

        tmp.unlink()
