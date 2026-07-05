"""Tests for P31 – AI Financial Analysis & Canvas visualization."""

import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.ai_service import (
    AIService,
    ActionProposal,
)
from mym.application.services.financial_analysis_service import (
    CanvasResponse,
    CanvasBlock,
    CanvasMetricCard,
    CanvasTable,
    CanvasChart,
    FinancialAnalysisService,
)
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import (
    AccountType,
    ActionRiskLevel,
    CategoryType,
    TransactionSource,
    TransactionStatus,
    TransactionRole,
)
from mym.infrastructure.database.db_manager import DatabaseManager


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


@pytest.fixture
def populated_session(db_mgr: DatabaseManager) -> Session:
    """Session with sample data for analysis testing."""
    s = db_mgr.new_session()

    # Create categories
    cats = {
        "餐饮": Category(name="餐饮", category_type=CategoryType.EXPENSE),
        "交通": Category(name="交通", category_type=CategoryType.EXPENSE),
        "购物": Category(name="购物", category_type=CategoryType.EXPENSE),
        "工资": Category(name="工资", category_type=CategoryType.INCOME),
        "兼职": Category(name="兼职", category_type=CategoryType.INCOME),
    }
    for c in cats.values():
        s.add(c)
    s.flush()

    # Create accounts
    cash = Account(name="现金", account_type=AccountType.ASSET, opening_balance=Decimal("10000"))
    bank = Account(name="银行卡", account_type=AccountType.ASSET, opening_balance=Decimal("50000"))
    s.add_all([cash, bank])
    s.flush()

    # Create transactions for 2025-07
    from datetime import datetime
    txs_data = [
        ("expense", date(2025, 7, 1), cats["餐饮"], cash, Decimal("-50"), "午餐"),
        ("expense", date(2025, 7, 2), cats["交通"], cash, Decimal("-30"), "地铁"),
        ("expense", date(2025, 7, 3), cats["餐饮"], cash, Decimal("-80"), "晚餐"),
        ("expense", date(2025, 7, 4), cats["购物"], cash, Decimal("-200"), "衣服"),
        ("expense", date(2025, 7, 5), cats["交通"], bank, Decimal("-15"), "公交"),
        ("income", date(2025, 7, 1), cats["工资"], bank, Decimal("5000"), "月薪"),
    ]

    for biz_type, tx_date, cat, acct, amt, desc in txs_data:
        tx = Transaction(
            business_type=biz_type,
            transaction_date=tx_date,
            source=TransactionSource.MANUAL,
            status=TransactionStatus.POSTED,
            description=desc,
        )
        s.add(tx)
        s.flush()

        line = TransactionLine(
            transaction_id=tx.id,
            account_id=acct.id,
            category_id=cat.id,
            signed_amount=amt,
            role=TransactionRole.DEBIT,
            memo=desc,
        )
        s.add(line)
        s.flush()

    s.commit()
    yield s
    s.close()


class TestCanvasTypes:
    """Test canvas data types and validation."""

    def test_metric_card_to_dict(self):
        card = CanvasMetricCard(label="收入", value="¥5000", trend="up", change_pct=Decimal("12.5"))
        d = card.to_dict()
        assert d["type"] == "metric_card"
        assert d["label"] == "收入"
        assert d["value"] == "¥5000"
        assert d["trend"] == "up"

    def test_table_to_dict(self):
        tbl = CanvasTable(
            title="支出明细",
            columns=["分类", "金额"],
            rows=[["餐饮", "¥100"], ["交通", "¥50"]],
        )
        d = tbl.to_dict()
        assert d["type"] == "table"
        assert len(d["rows"]) == 2

    def test_chart_to_dict(self):
        chart = CanvasChart(
            title="支出分布",
            chart_type="pie",
            labels=["餐饮", "交通"],
            series=[{"name": "金额", "data": [100, 50]}],
        )
        d = chart.to_dict()
        assert d["chart_type"] == "pie"

    def test_canvas_response_to_json(self):
        resp = CanvasResponse(title="分析报告")
        resp.blocks.append(CanvasBlock(text="测试"))
        json_str = resp.to_json()
        data = json.loads(json_str)
        assert data["canvas_version"] == "1.0"
        assert data["title"] == "分析报告"

    def test_canvas_validation_valid(self):
        data = {"canvas_version": "1.0", "title": "test", "blocks": []}
        errors = CanvasResponse.validate(data)
        assert len(errors) == 0

    def test_canvas_validation_missing_version(self):
        data = {"blocks": []}
        errors = CanvasResponse.validate(data)
        assert len(errors) > 0

    def test_canvas_validation_bad_version(self):
        data = {"canvas_version": "0.9", "blocks": []}
        errors = CanvasResponse.validate(data)
        assert len(errors) > 0

    def test_canvas_validation_missing_blocks(self):
        data = {"canvas_version": "1.0"}
        errors = CanvasResponse.validate(data)
        assert len(errors) > 0

    def test_canvas_validation_blocks_not_array(self):
        data = {"canvas_version": "1.0", "blocks": "not_array"}
        errors = CanvasResponse.validate(data)
        assert len(errors) > 0

    def test_canvas_validation_bad_block_type(self):
        data = {
            "canvas_version": "1.0",
            "blocks": [{"type": "raw_html", "content": "<script>alert(1)</script>"}],
        }
        errors = CanvasResponse.validate(data)
        assert len(errors) > 0


class TestFinancialAnalysisService:
    """Test the analysis query service."""

    def test_monthly_summary(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.monthly_summary(2025, 7)
        assert result["year"] == 2025
        assert result["month"] == 7
        assert Decimal(result["expense"]) > 0
        assert Decimal(result["income"]) > 0

    def test_category_breakdown(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.category_breakdown(2025, 7)
        assert len(result["categories"]) >= 2
        assert Decimal(result["total"]) > 0

    def test_income_breakdown(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.income_breakdown(2025, 7)
        assert len(result["categories"]) >= 1

    def test_account_cashflow(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.account_cashflow(2025, 7)
        assert len(result) >= 1

    def test_anomaly_detection(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.anomaly_detection(2025, 7)
        # With only one month of data, anomalies may or may not appear
        assert isinstance(result, list)

    def test_period_comparison(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.period_comparison(2025, 7)
        assert "current" in result
        assert "previous_month" in result

    def test_recent_transactions(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.recent_transactions(limit=5)
        assert len(result) <= 5
        assert len(result) >= 1

    def test_full_analysis(self, populated_session):
        fas = FinancialAnalysisService(populated_session)
        result = fas.full_analysis(2025, 7)
        assert "monthly_summary" in result
        assert "category_breakdown" in result
        assert "recent_transactions" in result

    def test_empty_month(self, session):
        """Analysis on empty data should return zeros, not crash."""
        fas = FinancialAnalysisService(session)
        result = fas.monthly_summary(2025, 1)
        assert Decimal(result["income"]) == 0
        assert Decimal(result["expense"]) == 0
        assert Decimal(result["net"]) == 0


class TestAIAnalysisActions:
    """Test that AI can trigger analysis actions."""

    def test_analyze_monthly_action(self, populated_session):
        svc = AIService(populated_session)
        spec = svc.get_action_spec("analyze_monthly")
        assert spec is not None
        assert spec.risk_level == ActionRiskLevel.LOW
        assert not spec.requires_confirmation

        proposal = ActionProposal(
            action="analyze_monthly",
            params={"year": 2025, "month": 7},
            risk_level=ActionRiskLevel.LOW,
            summary="月度分析",
            requires_confirmation=False,
        )
        result = svc.execute_action(proposal, 1)
        assert result["success"]
        assert result.get("canvas") is True
        assert "blocks" in result["data"]

    def test_analyze_anomaly_action(self, populated_session):
        svc = AIService(populated_session)
        proposal = ActionProposal(
            action="analyze_anomaly",
            params={"year": 2025, "month": 7},
            risk_level=ActionRiskLevel.LOW,
            summary="异常检测",
            requires_confirmation=False,
        )
        result = svc.execute_action(proposal, 1)
        assert result["success"]
        assert result.get("canvas") is True

    def test_analyze_full_action(self, populated_session):
        svc = AIService(populated_session)
        proposal = ActionProposal(
            action="analyze_full",
            params={"year": 2025, "month": 7},
            risk_level=ActionRiskLevel.LOW,
            summary="完整分析",
            requires_confirmation=False,
        )
        result = svc.execute_action(proposal, 1)
        assert result["success"]
        assert result.get("canvas") is True
        data = result["data"]
        assert len(data["blocks"]) >= 1

    def test_analyze_requires_valid_params(self, session):
        svc = AIService(session)
        spec = svc.get_action_spec("analyze_monthly")
        errors = spec.validate_params()
        assert len(errors) > 0  # missing required params

    def test_all_analysis_actions_registered(self, session):
        svc = AIService(session)
        actions = svc.get_all_actions()
        assert "analyze_monthly" in actions
        assert "analyze_category" in actions
        assert "analyze_anomaly" in actions
        assert "analyze_comparison" in actions
        assert "analyze_budget" in actions
        assert "analyze_full" in actions

    def test_analysis_action_audit(self, populated_session):
        svc = AIService(populated_session)
        proposal = ActionProposal(
            action="analyze_monthly",
            params={"year": 2025, "month": 7},
            risk_level=ActionRiskLevel.LOW,
            summary="测试分析",
            requires_confirmation=False,
        )
        result = svc.execute_action(proposal, 1)
        svc.record_audit("analyze_monthly", proposal, result)
        populated_session.flush()

        from mym.domain.entities.audit import AuditLog
        logs = populated_session.query(AuditLog).all()
        assert any("analyze" in log.action for log in logs)

    def test_canvas_not_raw_html(self, populated_session):
        """Ensure analysis output is controlled JSON, not raw HTML."""
        svc = AIService(populated_session)
        proposal = ActionProposal(
            action="analyze_full",
            params={"year": 2025, "month": 7},
            risk_level=ActionRiskLevel.LOW,
            summary="完整分析",
            requires_confirmation=False,
        )
        result = svc.execute_action(proposal, 1)
        data = result["data"]
        json_str = json.dumps(data)
        # No raw HTML tags
        assert "<script>" not in json_str
        assert "<iframe>" not in json_str
        # Should be valid canvas JSON
        errors = CanvasResponse.validate(data)
        assert len(errors) == 0
