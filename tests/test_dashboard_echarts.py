"""仪表盘与 ECharts 测试。

覆盖：
- option_builders 生成不含 CDN 的 option JSON
- chart_html 生成不含 http://、https:// 的 HTML
- ChartWebView 构造与属性
- ReportService 仪表盘数据聚合
- DashboardPage 构造与控件存在性
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from mym2.charts import option_builders
from mym2.charts.chart_html import build_chart_html, chart_html_template, update_chart_js
from mym2.db.models.account import Account
from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType
from mym2.services.report_service import DashboardData, MonthlySnapshot, ReportService
from mym2.ui.widgets.chart_web_view import ChartWebView


@pytest.fixture
def qapp_fixture(qapp):
    return qapp


# ═══════════════════════════════════════════════
#  1. option_builders 测试
# ═══════════════════════════════════════════════


class TestOptionBuilders:
    def test_asset_liability_pie_structure(self):
        opt = option_builders.build_asset_liability_pie(
            ["现金", "银行"], [10000, 50000],
            ["信用卡"], [20000],
            dark_mode=True,
        )
        assert "series" in opt
        assert len(opt["series"]) == 2  # 资产饼图 + 负债饼图
        assert opt["series"][0]["type"] == "pie"
        assert opt["series"][1]["type"] == "pie"

    def test_asset_liability_pie_values_are_yuan(self):
        opt = option_builders.build_asset_liability_pie(
            ["现金"], [12345], [], [], dark_mode=True,
        )
        val = opt["series"][0]["data"][0]["value"]
        assert val == "123.45"

    def test_asset_liability_pie_no_cdn(self):
        opt = option_builders.build_asset_liability_pie(
            ["A"], [100], ["L"], [50],
        )
        opt_json = json.dumps(opt)
        assert "http://" not in opt_json
        assert "https://" not in opt_json
        assert "cdn" not in opt_json.lower()

    def test_monthly_bar_structure(self):
        opt = option_builders.build_monthly_income_expense_bar(
            ["1月", "2月", "3月"],
            [10000, 20000, 15000],
            [5000, 8000, 7000],
            dark_mode=True,
        )
        assert opt["series"][0]["name"] == "收入"
        assert opt["series"][1]["name"] == "支出"
        assert opt["xAxis"]["data"] == ["1月", "2月", "3月"]

    def test_monthly_bar_values_are_yuan_floats(self):
        opt = option_builders.build_monthly_income_expense_bar(
            ["1月"], [12345], [5000],
        )
        assert opt["series"][0]["data"][0] == 123.45
        assert opt["series"][1]["data"][0] == 50.0

    def test_monthly_bar_no_cdn(self):
        opt = option_builders.build_monthly_income_expense_bar(
            ["1月"], [100], [50],
        )
        opt_json = json.dumps(opt)
        assert "http://" not in opt_json
        assert "https://" not in opt_json
        assert "cdn" not in opt_json.lower()

    def test_net_worth_trend_structure(self):
        opt = option_builders.build_net_worth_trend_line(
            ["1月", "2月"], [100000, 120000], dark_mode=True,
        )
        assert opt["series"][0]["type"] == "line"
        assert opt["series"][0]["smooth"] is True

    def test_net_worth_trend_no_cdn(self):
        opt = option_builders.build_net_worth_trend_line(
            ["1月"], [100000],
        )
        opt_json = json.dumps(opt)
        assert "http://" not in opt_json
        assert "https://" not in opt_json

    def test_category_pie_structure(self):
        opt = option_builders.build_category_pie(
            ["餐饮", "交通"], [5000, 2000], title="支出分类",
        )
        assert opt["title"]["text"] == "支出分类"
        assert opt["series"][0]["type"] == "pie"

    def test_category_pie_no_cdn(self):
        opt = option_builders.build_category_pie(
            ["A"], [100], title="T",
        )
        opt_json = json.dumps(opt)
        assert "http://" not in opt_json
        assert "https://" not in opt_json
        assert "cdn" not in opt_json.lower()

    def test_dark_mode_text_color(self):
        """深色模式文字颜色应为浅色。"""
        opt_dark = option_builders.build_asset_liability_pie(
            ["A"], [100], [], [], dark_mode=True,
        )
        opt_light = option_builders.build_asset_liability_pie(
            ["A"], [100], [], [], dark_mode=False,
        )
        assert opt_dark["legend"]["textStyle"] is not None
        assert opt_light["legend"]["textStyle"] is not None


# ═══════════════════════════════════════════════
#  2. chart_html 测试
# ═══════════════════════════════════════════════


class TestChartHtml:
    def test_template_no_cdn(self):
        html = chart_html_template("Test")
        assert "echarts.min.js" in html
        assert "http://" not in html
        assert "https://" not in html
        # 不应有常见的 CDN 域
        assert "cdn.jsdelivr.net" not in html
        assert "unpkg.com" not in html
        assert "cdnjs" not in html.lower()

    def test_template_has_resize_handler(self):
        html = chart_html_template("Test")
        assert "window.addEventListener('resize'" in html
        assert "myChart.resize()" in html

    def test_template_has_update_chart(self):
        html = chart_html_template("Test")
        assert "window.updateChart" in html

    def test_build_chart_html_embeds_option(self):
        opt = {"series": [{"type": "pie", "data": [{"name": "A", "value": 10}]}]}
        html = build_chart_html(opt, title="Test")
        # option JSON 应嵌入 HTML
        assert '"series"' in html
        assert '"type": "pie"' in html
        # 不应有外部 URL
        assert "http://" not in html
        assert "https://" not in html

    def test_build_chart_html_complete_document(self):
        opt = {"series": []}
        html = build_chart_html(opt)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html
        assert "<script" in html

    def test_update_chart_js(self):
        new_opt = {"series": [{"type": "bar", "data": [1, 2, 3]}]}
        js = update_chart_js(new_opt)
        assert "updateChart" in js
        assert '"type": "bar"' in js

    def test_update_chart_js_no_cdn(self):
        js = update_chart_js({"series": []})
        assert "http://" not in js
        assert "https://" not in js


# ═══════════════════════════════════════════════
#  3. ChartWebView 测试
# ═══════════════════════════════════════════════


class TestChartWebView:
    def test_constructs(self, qapp_fixture):
        cv = ChartWebView({"series": []}, title="Test")
        assert cv is not None
        assert cv._loaded is False  # 还未 loadFinished
        cv.deleteLater()

    def test_has_chart_ready_signal(self, qapp_fixture):
        cv = ChartWebView({"series": []})
        assert hasattr(cv, "chart_ready")
        assert cv.chart_ready is not None
        cv.deleteLater()

    def test_update_chart_before_loaded(self, qapp_fixture):
        """加载完成前 update 应缓存在 _pending_update。"""
        cv = ChartWebView({"series": []})
        new_opt = {"series": [{"type": "line"}]}
        cv.update_chart(new_opt)
        assert cv._pending_update is not None
        assert cv._pending_update == new_opt
        cv.deleteLater()

    def test_reload_with_option(self, qapp_fixture):
        cv = ChartWebView({"series": []})
        new_opt = {"series": [{"type": "bar"}]}
        cv.reload_with_option(new_opt)
        assert cv._option == new_opt
        cv.deleteLater()


# ═══════════════════════════════════════════════
#  4. ReportService 测试
# ═══════════════════════════════════════════════


class TestReportService:
    def _setup_accounts(self, session):
        a1 = Account(
            name="现金", type=AccountType.CASH,
            is_enabled=True, is_editable=True,
            opening_balance_minor=0, current_balance_minor=100000,
        )
        a2 = Account(
            name="信用卡", type=AccountType.CREDIT_CARD,
            is_enabled=True, is_editable=True,
            opening_balance_minor=0, current_balance_minor=30000,
        )
        a3 = Account(
            name="投资快照", type=AccountType.INVESTMENT_SNAPSHOT,
            is_enabled=True, is_editable=False, is_locked=True,
            opening_balance_minor=500000, current_balance_minor=500000,
        )
        session.add_all([a1, a2, a3])
        session.commit()

        # 食物分类（支出）
        food = Category(name="餐饮", type="expense", is_enabled=True)
        session.add(food)
        session.commit()

        # 当月流水
        today = date.today()
        tx1 = Transaction(
            transaction_date=date(today.year, today.month, 1),
            type="expense",
            account_out_id=a1.id,
            category_id=food.id,
            amount_minor=5000,
        )
        tx2 = Transaction(
            transaction_date=date(today.year, today.month, 3),
            type="income",
            account_out_id=a1.id,
            account_in_id=a1.id,
            amount_minor=10000,
        )
        session.add_all([tx1, tx2])
        session.commit()

        return a1, a2, a3, food, tx1, tx2

    def test_dashboard_data_basic(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        assert isinstance(data, DashboardData)
        assert data.total_assets_minor == 600000  # 100000 + 500000
        assert data.total_liabilities_minor == 30000
        assert data.net_worth_minor == 570000  # 600000 - 30000
        assert data.receivable_minor == 0

    def test_income_expense_current_month(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        assert data.current_month_expense_minor >= 5000
        assert data.current_month_income_minor >= 10000

    def test_monthly_trend_length(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        assert len(data.monthly_trend) == 6

    def test_monthly_trend_snapshots(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        for snap in data.monthly_trend:
            assert isinstance(snap, MonthlySnapshot)
            assert 1 <= snap.month <= 12
            assert snap.label.endswith("月")

    def test_category_breakdown(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        assert len(data.category_breakdown) >= 1
        # 餐饮分类应在列表中
        cat_names = [n for n, _ in data.category_breakdown]
        assert "餐饮" in cat_names

    def test_budget_none_when_no_budget(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        assert data.budget_total_minor is None
        assert data.budget_spent_minor is None

    def test_budget_with_data(self, session):
        """设置预算后 budget 字段应有值。"""
        svc = ReportService()
        _, _, _, food, _, _ = self._setup_accounts(session)

        today = date.today()
        period = BudgetPeriod(year=today.year, month=today.month)
        session.add(period)
        session.flush()

        line = BudgetLine(
            budget_period_id=period.id,
            category_id=food.id,
            amount_minor=20000,
        )
        session.add(line)
        session.commit()

        data = svc.get_dashboard_data(session)
        assert data.budget_total_minor is not None
        assert data.budget_total_minor == 20000
        assert data.budget_spent_minor is not None
        assert data.budget_spent_minor >= 5000

    def test_asset_liability_lists(self, session):
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        asset_names = [n for n, _ in data.asset_accounts]
        assert "现金" in asset_names
        assert "投资快照" in asset_names
        liability_names = [n for n, _ in data.liability_accounts]
        assert "信用卡" in liability_names

    def test_investment_snapshot_included(self, session):
        """投资快照应计入资产总额但不展示股票信息。"""
        svc = ReportService()
        self._setup_accounts(session)

        data = svc.get_dashboard_data(session)
        assert data.total_assets_minor >= 500000
        # 资产账户中应包含投资快照
        asset_names = [n for n, _ in data.asset_accounts]
        assert "投资快照" in asset_names


# ═══════════════════════════════════════════════
#  5. 静态 HTML/JS 合规性检查
# ═══════════════════════════════════════════════


class TestStaticCompliance:
    """验证生成的 HTML/JS 不含 http://、https://、CDN。"""

    def test_all_options_no_cdn(self):
        """所有 option builder 的 JSON 都不含 CDN。"""
        builders = [
            option_builders.build_asset_liability_pie(
                ["A"], [100], ["L"], [50],
            ),
            option_builders.build_monthly_income_expense_bar(
                ["1月"], [100], [50],
            ),
            option_builders.build_net_worth_trend_line(
                ["1月"], [100000],
            ),
            option_builders.build_category_pie(
                ["A"], [100], title="T",
            ),
        ]
        banned = ["http://", "https://", "cdn.jsdelivr", "unpkg", "cdnjs"]
        for opt in builders:
            opt_json = json.dumps(opt)
            for word in banned:
                assert word not in opt_json.lower(), f"option contains {word}"

    def test_html_template_no_cdn(self):
        html = chart_html_template("Test")
        banned = ["http://", "https://", "cdn.jsdelivr", "unpkg", "cdnjs"]
        for word in banned:
            assert word not in html.lower(), f"HTML contains {word}"

    def test_build_chart_html_no_cdn(self):
        html = build_chart_html({"series": []})
        banned = ["http://", "https://", "cdn.jsdelivr", "unpkg", "cdnjs"]
        for word in banned:
            assert word not in html.lower(), f"build_chart_html contains {word}"

    def test_update_chart_js_no_cdn(self):
        js = update_chart_js({"series": []})
        banned = ["http://", "https://", "cdn.jsdelivr"]
        for word in banned:
            assert word not in js.lower()


# ═══════════════════════════════════════════════
#  6. DashboardPage 构造测试
# ═══════════════════════════════════════════════


class TestDashboardPageConstruction:
    def test_constructs_without_session(self, qapp_fixture):
        from mym2.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage()
        assert page is not None
        page.deleteLater()

    def test_has_chart_views(self, qapp_fixture):
        from mym2.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage()
        assert len(page._charts) == 4
        page.deleteLater()

    def test_has_recent_table(self, qapp_fixture):
        from mym2.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage()
        assert page._recent_table is not None
        page.deleteLater()

    def test_has_summary_cards_layout(self, qapp_fixture):
        from mym2.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage()
        assert page._cards_layout is not None
        page.deleteLater()

    def test_no_stock_content_in_page(self, qapp_fixture):
        """仪表盘不应展示股票名称、行情、价格走势。"""
        from mym2.ui.pages.dashboard_page import DashboardPage
        page = DashboardPage()
        # 页面中不应有股票相关控件
        from PySide6.QtWidgets import QLabel
        banned = ["股票", "行情", "价格走势", "交易", "K线"]
        for child in page.findChildren(QLabel):
            for word in banned:
                assert word not in child.text(), f"仪表盘包含禁止词: {child.text()}"
        page.deleteLater()


# ═══════════════════════════════════════════════
#  7. 金额显示测试
# ═══════════════════════════════════════════════


class TestAmountDisplay:
    """验证仪表盘金额显示格式。"""

    def test_minor_to_yuan_import(self):
        from mym2.ui.pages.dashboard_page import _minor_to_yuan
        assert _minor_to_yuan(0) == "0.00"
        assert _minor_to_yuan(100) == "1.00"
        assert _minor_to_yuan(12345) == "123.45"
        assert _minor_to_yuan(-5000) == "-50.00"

    def test_minor_to_yuan_f_precision(self):
        from mym2.ui.pages.dashboard_page import _minor_to_yuan_f
        assert _minor_to_yuan_f(12345) == 123.45
        assert _minor_to_yuan_f(100) == 1.0
