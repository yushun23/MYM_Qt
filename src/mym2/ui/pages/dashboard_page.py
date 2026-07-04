"""仪表盘页面 — 净资产概览、月度收支、图表卡片、最近流水。

图表使用本地离线 ECharts（QWebEngineView + echarts.min.js）。
资产构成包含投资快照但不展示股票名称/行情。
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym2.charts import option_builders
from mym2.db.session import get_session
from mym2.services.report_service import DashboardData, ReportService
from mym2.ui.widgets.chart_web_view import ChartWebView

logger = logging.getLogger("mym2.ui.dashboard_page")

_CARD_STYLE = """
QFrame#summaryCard {
    background: #2b2d3e;
    border-radius: 8px;
    padding: 12px;
}
"""


def _minor_to_yuan(minor: int) -> str:
    """整数分 → 元显示。"""
    sign = "-" if minor < 0 else ""
    val = abs(minor)
    yuan = val // 100
    fen = val % 100
    return f"{sign}{yuan}.{fen:02d}"


def _minor_to_yuan_f(minor: int) -> float:
    """整数分 → 元浮点数。"""
    return minor / 100


def _make_summary_card(title: str, value: str, color: str = "#fff") -> QFrame:
    """创建概览卡片。

    Args:
        title: 卡片标题（如"净资产"）。
        value: 显示值（已格式化）。
        color: 数值颜色。

    Returns:
        QFrame 卡片。
    """
    card = QFrame()
    card.setObjectName("summaryCard")
    card.setStyleSheet(_CARD_STYLE)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)

    title_label = QLabel(title)
    title_label.setStyleSheet("color: #999; font-size: 12px;")
    layout.addWidget(title_label)

    value_label = QLabel(value)
    value_label.setStyleSheet(f"color: {color}; font-size: 20px; font-weight: bold;")
    layout.addWidget(value_label)

    return card


def _make_section_title(text: str) -> QLabel:
    """创建区块标题。"""
    label = QLabel(text)
    label.setStyleSheet("color: #ddd; font-size: 16px; font-weight: bold; margin-top: 8px;")
    return label


class DashboardPage(QWidget):
    """仪表盘主页面。

    包含：概览卡片、资产负债饼图、月度收支柱状图、
          净资产趋势折线图、分类支出饼图、最近流水。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report_service = ReportService()
        self._data: DashboardData | None = None
        self._charts: list[ChartWebView] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        # 外层滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        self._main_layout = QVBoxLayout(container)
        self._main_layout.setContentsMargins(16, 16, 16, 16)
        self._main_layout.setSpacing(12)

        # 标题
        title = QLabel("仪表盘")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #fff;")
        self._main_layout.addWidget(title)

        # ── 概览卡片行 ──
        self._cards_layout = QGridLayout()
        self._cards_layout.setSpacing(10)
        self._main_layout.addLayout(self._cards_layout)

        # ── 图表行 1: 资产负债饼图 + 月度收支柱状图 ──
        self._main_layout.addWidget(_make_section_title("资产与负债"))

        chart_row_1 = QHBoxLayout()
        chart_row_1.setSpacing(10)

        self._pie_chart = ChartWebView(title="资产负债构成")
        self._pie_chart.setMinimumHeight(300)
        self._pie_chart.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chart_row_1.addWidget(self._pie_chart)

        self._bar_chart = ChartWebView(title="月度收支")
        self._bar_chart.setMinimumHeight(300)
        self._bar_chart.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chart_row_1.addWidget(self._bar_chart)

        self._charts.extend([self._pie_chart, self._bar_chart])
        self._main_layout.addLayout(chart_row_1)

        # ── 图表行 2: 净资产趋势 + 分类支出 ──
        self._main_layout.addWidget(_make_section_title("趋势与分类"))

        chart_row_2 = QHBoxLayout()
        chart_row_2.setSpacing(10)

        self._line_chart = ChartWebView(title="净资产趋势")
        self._line_chart.setMinimumHeight(300)
        self._line_chart.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chart_row_2.addWidget(self._line_chart)

        self._category_pie = ChartWebView(title="分类支出")
        self._category_pie.setMinimumHeight(300)
        self._category_pie.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chart_row_2.addWidget(self._category_pie)

        self._charts.extend([self._line_chart, self._category_pie])
        self._main_layout.addLayout(chart_row_2)

        # ── 最近流水表格 ──
        self._main_layout.addWidget(_make_section_title("最近流水"))
        self._recent_table = QTableView()
        self._recent_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self._recent_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._recent_table.horizontalHeader().setStretchLastSection(True)
        self._recent_table.verticalHeader().setVisible(False)
        self._recent_table.setMaximumHeight(200)
        self._recent_model = _RecentTxModel()
        self._recent_table.setModel(self._recent_model)
        self._main_layout.addWidget(self._recent_table)

        self._main_layout.addStretch()

        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """刷新仪表盘数据。"""
        try:
            session = get_session()
            try:
                self._data = self._report_service.get_dashboard_data(session)
            finally:
                session.close()
        except Exception as e:
            logger.warning("仪表盘数据加载失败: %s", e)
            return

        self._update_summary_cards()
        self._update_charts()
        self._update_recent_tx()

    def _update_summary_cards(self) -> None:
        """更新概览卡片。"""
        d = self._data
        if d is None:
            return

        # 清空现有卡片
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cards = [
            ("净资产", _minor_to_yuan(d.net_worth_minor), "#4a6cf7"),
            ("总资产", _minor_to_yuan(d.total_assets_minor), "#98c379"),
            ("总负债", _minor_to_yuan(d.total_liabilities_minor), "#e06c75"),
            ("应收款", _minor_to_yuan(d.receivable_minor), "#e5c07b"),
            ("本月收入", _minor_to_yuan(d.current_month_income_minor), "#56b6c2"),
            ("本月支出", _minor_to_yuan(d.current_month_expense_minor), "#e06c75"),
        ]

        for i, (title, value, color) in enumerate(cards):
            card = _make_summary_card(title, value, color)
            self._cards_layout.addWidget(card, i // 3, i % 3)

    def _update_charts(self) -> None:
        """更新四个图表。"""
        d = self._data
        if d is None:
            return

        # 1. 资产负债饼图
        if d.asset_accounts or d.liability_accounts:
            a_labels = [n for n, _ in d.asset_accounts]
            a_vals = [v for _, v in d.asset_accounts]
            l_labels = [n for n, _ in d.liability_accounts]
            l_vals = [v for _, v in d.liability_accounts]
            opt = option_builders.build_asset_liability_pie(
                a_labels, a_vals, l_labels, l_vals, dark_mode=True
            )
            self._pie_chart.update_chart(opt)

        # 2. 月度收支柱状图
        if d.monthly_trend:
            months = [s.label for s in d.monthly_trend]
            incomes = [s.income_minor for s in d.monthly_trend]
            expenses = [s.expense_minor for s in d.monthly_trend]
            opt = option_builders.build_monthly_income_expense_bar(
                months, incomes, expenses, dark_mode=True
            )
            self._bar_chart.update_chart(opt)

        # 3. 净资产趋势折线图
        if d.monthly_trend:
            months = [s.label for s in d.monthly_trend]
            net_worths = [s.net_worth_minor for s in d.monthly_trend]
            opt = option_builders.build_net_worth_trend_line(
                months, net_worths, dark_mode=True
            )
            self._line_chart.update_chart(opt)

        # 4. 分类支出饼图
        if d.category_breakdown:
            labels = [n for n, _ in d.category_breakdown]
            values = [v for _, v in d.category_breakdown]
            opt = option_builders.build_category_pie(
                labels, values, title="当月支出分类", dark_mode=True
            )
            self._category_pie.update_chart(opt)

    def _update_recent_tx(self) -> None:
        """更新最近流水表格。"""
        if self._data is None:
            return

        session = get_session()
        try:
            from sqlalchemy import select

            from mym2.db.models.transaction import Transaction

            txs = list(
                session.scalars(
                    select(Transaction)
                    .order_by(
                        Transaction.transaction_date.desc(),
                        Transaction.created_at.desc(),
                    )
                    .limit(10)
                )
            )

            # 加载关联数据
            account_ids = set()
            cat_ids = set()
            for tx in txs:
                account_ids.add(tx.account_out_id)
                if tx.account_in_id:
                    account_ids.add(tx.account_in_id)
                if tx.category_id:
                    cat_ids.add(tx.category_id)

            from mym2.db.models.account import Account
            from mym2.db.models.category import Category

            acct_map = {}
            if account_ids:
                accts = list(
                    session.scalars(
                        select(Account).where(Account.id.in_(account_ids))
                    )
                )
                acct_map = {a.id: a.name for a in accts}

            cat_map = {}
            if cat_ids:
                cats = list(
                    session.scalars(
                        select(Category).where(Category.id.in_(cat_ids))
                    )
                )
                cat_map = {c.id: c.name for c in cats}

            rows = []
            for tx in txs:
                rows.append({
                    "date": str(tx.transaction_date),
                    "type": tx.type,
                    "amount": _minor_to_yuan(tx.amount_minor),
                    "account": acct_map.get(tx.account_out_id, ""),
                    "category": cat_map.get(tx.category_id, "") if tx.category_id else "",
                    "note": tx.note or "",
                })

            self._recent_model.load_data(rows)
        finally:
            session.close()


# ── 最近流水小表格模型 ──

class _RecentTxModel(QAbstractTableModel):
    """最近流水简化表格模型。"""

    COLUMNS = ["日期", "类型", "金额", "账户", "分类", "备注"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    def load_data(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=None) -> int:
        return len(self._rows)

    def columnCount(self, parent=None) -> int:
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        keys = ["date", "type", "amount", "account", "category", "note"]
        if role == Qt.DisplayRole:
            return row.get(keys[col], "")
        return None
