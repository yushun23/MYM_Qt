"""Dashboard page – asset/liability/net worth overview with recent transactions."""

import logging
from decimal import Decimal

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.dashboard_query import DashboardQueryService, DashboardSummary
from mym.ui.navigation import AppEventBus
from mym.ui.widgets.table_model import BaseTableModel, ColumnDef

logger = logging.getLogger(__name__)


class _DashboardWorker(QObject):
    """Background worker that queries dashboard data without freezing UI."""

    finished = Signal(object)  # emits DashboardSummary

    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory

    @Slot()
    def run(self) -> None:
        session = self._session_factory()
        try:
            svc = DashboardQueryService(session)
            summary = svc.get_summary()
            self.finished.emit(summary)
        except Exception as e:
            logger.exception("Dashboard query failed: %s", e)
        finally:
            session.close()


class _MetricCard(QFrame):
    """A single metric card showing label and value."""

    def __init__(self, label: str, value_text: str, accent: str = "#1976D2", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setMinimumHeight(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        value_label = QLabel(value_text)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {accent};")

        name_label = QLabel(label)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("font-size: 12px;")

        layout.addWidget(value_label)
        layout.addWidget(name_label)


class DashboardPage(QWidget):
    """Dashboard showing financial overview."""

    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._worker: QThread | None = None
        self._setup_ui()

        # Listen for ledger changes
        AppEventBus.instance().ledger_changed.connect(self.refresh)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)

        # Metric cards row
        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)

        self._asset_card = _MetricCard("总资产", "—")
        self._liability_card = _MetricCard("总负债", "—", "#D32F2F")
        self._networth_card = _MetricCard("净资产", "—", "#2E7D32")
        self._cash_card = _MetricCard("现金余额", "—")
        self._receivable_card = _MetricCard("应收余额", "—", "#ED6C02")
        self._income_card = _MetricCard("本月收入", "—", "#2E7D32")
        self._expense_card = _MetricCard("本月支出", "—", "#D32F2F")

        cards_layout.addWidget(self._asset_card, 0, 0)
        cards_layout.addWidget(self._liability_card, 0, 1)
        cards_layout.addWidget(self._networth_card, 0, 2)
        cards_layout.addWidget(self._cash_card, 1, 0)
        cards_layout.addWidget(self._receivable_card, 1, 1)
        cards_layout.addWidget(self._income_card, 1, 2)
        cards_layout.addWidget(self._expense_card, 1, 3)
        content_layout.addLayout(cards_layout)

        # Recent transactions section
        section_label = QLabel("最近流水")
        section_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 12px;")
        content_layout.addWidget(section_label)

        tx_columns = [
            ColumnDef("date", "日期", 100),
            ColumnDef("type", "类型", 60),
            ColumnDef("amount", "金额", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("description", "备注", 300),
        ]
        self._tx_model = BaseTableModel(tx_columns)
        self._tx_table = QTableView()
        self._tx_table.setModel(self._tx_model)
        self._tx_table.horizontalHeader().setStretchLastSection(True)
        self._tx_table.setMaximumHeight(300)
        content_layout.addWidget(self._tx_table)

        content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def on_enter(self) -> None:
        self.refresh()

    def on_leave(self) -> None:
        pass

    def refresh(self) -> None:
        """Trigger a background query for dashboard data."""
        if self._worker and self._worker.isRunning():
            return  # Already loading

        self._thread = QThread()
        self._worker_obj = _DashboardWorker(self._session_factory)
        self._worker_obj.moveToThread(self._thread)

        self._thread.started.connect(self._worker_obj.run)
        self._worker_obj.finished.connect(self._on_data_loaded)
        self._worker_obj.finished.connect(self._thread.quit)
        self._worker_obj.finished.connect(self._worker_obj.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    @Slot(object)
    def _on_data_loaded(self, summary: DashboardSummary) -> None:
        """Update UI with loaded dashboard data."""
        fmt = lambda d: f"¥{d:,.2f}"

        self._asset_card.findChildren(QLabel)[0].setText(fmt(summary.total_assets))
        self._liability_card.findChildren(QLabel)[0].setText(fmt(summary.total_liabilities))
        self._networth_card.findChildren(QLabel)[0].setText(fmt(summary.net_worth))
        self._cash_card.findChildren(QLabel)[0].setText(fmt(summary.cash_balance))
        self._receivable_card.findChildren(QLabel)[0].setText(fmt(summary.receivable_balance))
        self._income_card.findChildren(QLabel)[0].setText(fmt(summary.income_this_month))
        self._expense_card.findChildren(QLabel)[0].setText(fmt(summary.expense_this_month))

        # Format recent transactions
        type_labels = {
            "income": "收入", "expense": "支出", "transfer": "转账",
            "lend": "垫付", "recover": "收回", "balance_adjustment": "调整",
            "stock_profit": "投资盈利", "stock_loss": "投资亏损",
        }
        tx_data = []
        for tx in summary.recent_transactions:
            tx_data.append({
                "date": tx["date"],
                "type": type_labels.get(tx["type"], tx["type"]),
                "amount": str(tx["amount"]),
                "description": tx["description"],
            })
        self._tx_model.set_data(tx_data)
