"""ReportPage – income/expense reports, balance sheet, export/drill-down."""

import logging
from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym.application.dto.report_dto import BalanceSheetSnapshot, IncomeExpenseSummary, ReportPeriodDTO
from mym.application.services.balance_sheet_query import BalanceSheetQueryService
from mym.application.services.export_service import ExportService, build_table_html
from mym.application.services.report_query import ReportQueryService
from mym.ui.navigation import AppEventBus, PageKey
from mym.ui.widgets.chart_host import (
    ChartHostWidget,
    build_bar_option,
    build_line_option,
    build_pie_option,
)
from mym.ui.widgets.print_preview import PrintPreviewDialog
from mym.ui.widgets.table_model import BaseTableModel, ColumnDef

logger = logging.getLogger(__name__)


class _ReportWorker(QObject):
    """Background worker for report queries."""
    finished = Signal(object, object)  # (IncomeExpenseSummary, BalanceSheetSnapshot)

    def __init__(self, session_factory, start_date: date, end_date: date, as_of_date: date,
                 parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._start = start_date
        self._end = end_date
        self._as_of = as_of_date

    @Slot()
    def run(self) -> None:
        session = self._session_factory()
        try:
            # Income/Expense report
            report_svc = ReportQueryService(session)
            period = ReportPeriodDTO(self._start, self._end)
            summary = report_svc.get_income_expense_report(period)

            # Balance sheet
            bs_svc = BalanceSheetQueryService(session)
            snapshot = bs_svc.get_balance_sheet(self._as_of)

            self.finished.emit(summary, snapshot)
        except Exception as e:
            logger.exception("Report query failed: %s", e)
        finally:
            session.close()


class ReportPage(QWidget):
    """Full report center with income/expense, balance sheet, and export."""

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._summary: IncomeExpenseSummary | None = None
        self._snapshot: BalanceSheetSnapshot | None = None
        self._worker: QThread | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # ── Controls ──
        ctrl_frame = QFrame()
        ctrl_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        ctrl_layout = QHBoxLayout(ctrl_frame)

        ctrl_layout.addWidget(QLabel("起始:"))
        self._start_edit = QDateEdit(QDate.currentDate().addMonths(-1))
        self._start_edit.setCalendarPopup(True)
        self._start_edit.setDisplayFormat("yyyy-MM-dd")
        ctrl_layout.addWidget(self._start_edit)

        ctrl_layout.addWidget(QLabel("截止:"))
        self._end_edit = QDateEdit(QDate.currentDate())
        self._end_edit.setCalendarPopup(True)
        self._end_edit.setDisplayFormat("yyyy-MM-dd")
        ctrl_layout.addWidget(self._end_edit)

        # Quick intervals
        self._interval_combo = QComboBox()
        self._interval_combo.addItems([
            "自定义", "本月", "上月", "本季", "本年", "最近30天", "最近90天"
        ])
        self._interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        ctrl_layout.addWidget(self._interval_combo)

        self._query_btn = QPushButton("查询")
        self._query_btn.clicked.connect(self._on_query)
        ctrl_layout.addWidget(self._query_btn)

        self._export_pdf_btn = QPushButton("打印预览")
        self._export_pdf_btn.clicked.connect(self._on_print_preview)
        ctrl_layout.addWidget(self._export_pdf_btn)

        self._export_csv_btn = QPushButton("导出CSV")
        self._export_csv_btn.clicked.connect(self._on_export_csv)
        ctrl_layout.addWidget(self._export_csv_btn)

        ctrl_layout.addStretch()
        main_layout.addWidget(ctrl_frame)

        # ── Metric cards ──
        cards = QGridLayout()
        self._income_card = self._make_card("总收入", "—", "#2E7D32")
        self._expense_card = self._make_card("总支出", "—", "#D32F2F")
        self._net_card = self._make_card("结余", "—", "#1976D2")
        self._asset_card = self._make_card("总资产", "—", "#1565C0")
        self._liability_card = self._make_card("总负债", "—", "#D32F2F")
        self._nw_card = self._make_card("净资产", "—", "#2E7D32")
        cards.addWidget(self._income_card, 0, 0)
        cards.addWidget(self._expense_card, 0, 1)
        cards.addWidget(self._net_card, 0, 2)
        cards.addWidget(self._asset_card, 0, 3)
        cards.addWidget(self._liability_card, 0, 4)
        cards.addWidget(self._nw_card, 0, 5)
        main_layout.addLayout(cards)

        # ── Tabs: Charts / Table ──
        tabs = QTabWidget()

        # Chart tab
        chart_tab = QWidget()
        chart_layout = QVBoxLayout(chart_tab)
        chart_tabs = QTabWidget()

        # Income/Expense bar chart
        self._bar_chart = ChartHostWidget()
        chart_tabs.addTab(self._bar_chart, "月度收支")

        # Category pie chart
        self._pie_chart = ChartHostWidget()
        chart_tabs.addTab(self._pie_chart, "分类支出")

        # Net worth trend
        self._line_chart = ChartHostWidget()
        chart_tabs.addTab(self._line_chart, "趋势")

        chart_layout.addWidget(chart_tabs)

        # Bar chart click → we use signal to filter transactions
        self._bar_chart.chartClicked.connect(self._on_chart_clicked)

        tabs.addTab(chart_tab, "图表")

        # Detail table tab
        table_tab = QWidget()
        table_layout = QVBoxLayout(table_tab)
        tx_columns = [
            ColumnDef("date", "日期", 100),
            ColumnDef("type", "类型", 80),
            ColumnDef("amount", "金额", 120, Qt.AlignmentFlag.AlignRight),
            ColumnDef("description", "备注", 300),
        ]
        self._tx_model = BaseTableModel(tx_columns)
        self._tx_table = QTableView()
        self._tx_table.setModel(self._tx_model)
        self._tx_table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self._tx_table)
        tabs.addTab(table_tab, "明细")

        # Balance sheet tab
        bs_tab = QWidget()
        bs_layout = QVBoxLayout(bs_tab)
        self._bs_label = QLabel("资产负债表")
        self._bs_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        bs_layout.addWidget(self._bs_label)
        bs_columns = [
            ColumnDef("group", "分组", 100),
            ColumnDef("name", "账户", 150),
            ColumnDef("balance", "余额", 120, Qt.AlignmentFlag.AlignRight),
        ]
        self._bs_model = BaseTableModel(bs_columns)
        self._bs_table = QTableView()
        self._bs_table.setModel(self._bs_model)
        self._bs_table.horizontalHeader().setStretchLastSection(True)
        bs_layout.addWidget(self._bs_table)

        # Valuation warning
        self._bs_warning = QLabel("")
        self._bs_warning.setStyleSheet("color: #ED6C02; font-style: italic;")
        self._bs_warning.setWordWrap(True)
        bs_layout.addWidget(self._bs_warning)

        tabs.addTab(bs_tab, "资产负债表")

        main_layout.addWidget(tabs)

    def _make_card(self, label: str, value: str, accent: str) -> QFrame:
        card = QFrame()
        card.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        card.setMinimumHeight(80)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        val_lbl = QLabel(value)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {accent};")
        val_lbl.setObjectName(f"card_value_{label}")
        name_lbl = QLabel(label)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(val_lbl)
        layout.addWidget(name_lbl)
        card._value_label = val_lbl
        return card

    def _on_interval_changed(self, idx: int) -> None:
        if idx == 0:  # Custom
            return
        today = QDate.currentDate()
        name = self._interval_combo.currentText()
        if name == "本月":
            self._start_edit.setDate(QDate(today.year(), today.month(), 1))
            self._end_edit.setDate(today)
        elif name == "上月":
            prev = today.addMonths(-1)
            self._start_edit.setDate(QDate(prev.year(), prev.month(), 1))
            last_day = QDate(prev.year(), prev.month(), prev.daysInMonth())
            self._end_edit.setDate(last_day)
        elif name == "本季":
            q = (today.month() - 1) // 3
            self._start_edit.setDate(QDate(today.year(), q * 3 + 1, 1))
            self._end_edit.setDate(today)
        elif name == "本年":
            self._start_edit.setDate(QDate(today.year(), 1, 1))
            self._end_edit.setDate(today)
        elif name == "最近30天":
            self._start_edit.setDate(today.addDays(-30))
            self._end_edit.setDate(today)
        elif name == "最近90天":
            self._start_edit.setDate(today.addDays(-90))
            self._end_edit.setDate(today)

    def _on_query(self) -> None:
        """Trigger background report query."""
        q_start = self._start_edit.date().toPython()
        q_end = self._end_edit.date().toPython()

        if self._worker and getattr(self._worker, 'isRunning', lambda: False)():
            return

        self._query_btn.setEnabled(False)
        self._query_btn.setText("查询中...")

        self._thread = QThread()
        self._worker_obj = _ReportWorker(
            self._session_factory, q_start, q_end, q_end
        )
        self._worker_obj.moveToThread(self._thread)
        self._thread.started.connect(self._worker_obj.run)
        self._worker_obj.finished.connect(self._on_data_loaded)
        self._worker_obj.finished.connect(self._thread.quit)
        self._worker_obj.finished.connect(self._worker_obj.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(object, object)
    def _on_data_loaded(self, summary: IncomeExpenseSummary,
                        snapshot: BalanceSheetSnapshot) -> None:
        """Update all UI elements with loaded data."""
        self._summary = summary
        self._snapshot = snapshot
        self._query_btn.setEnabled(True)
        self._query_btn.setText("查询")

        fmt = lambda d: f"¥{Decimal(d):,.2f}"

        # Metric cards
        self._income_card._value_label.setText(fmt(summary.total_income))
        self._expense_card._value_label.setText(fmt(summary.total_expense))
        self._net_card._value_label.setText(fmt(summary.net_balance))
        self._asset_card._value_label.setText(fmt(snapshot.total_assets))
        self._liability_card._value_label.setText(fmt(snapshot.total_liabilities))
        self._nw_card._value_label.setText(fmt(snapshot.net_worth))

        # Bar chart: monthly trend
        months = [m["month"] for m in summary.monthly_trend]
        incomes = [float(m["income"]) for m in summary.monthly_trend]
        expenses = [float(m["expense"]) for m in summary.monthly_trend]
        self._bar_chart.set_option(build_bar_option(months, incomes, title="月度收入"))

        # Pie chart: category breakdown (expense)
        if summary.category_breakdown_expense:
            pie_data = [{"name": c["name"], "value": float(c["value"])}
                        for c in summary.category_breakdown_expense[:10]]
            self._pie_chart.set_option(build_pie_option(pie_data, title="分类支出"))
        else:
            self._pie_chart.set_option(None)

        # Line chart: trend
        if len(months) > 1:
            self._line_chart.set_option(build_line_option(
                months,
                [
                    {"name": "收入", "data": incomes, "color": "#2E7D32"},
                    {"name": "支出", "data": expenses, "color": "#D32F2F"},
                ],
                title="收支趋势",
            ))
        else:
            self._line_chart.set_option(None)

        # Transaction detail table
        tx_type_labels = {
            "income": "收入", "expense": "支出", "transfer": "转账",
            "lend": "垫付", "recover": "收回",
            "stock_profit": "投资盈利", "stock_loss": "投资亏损",
            "balance_adjustment": "调整",
        }
        tx_data = []
        for tx in summary.transaction_details:
            tx_data.append({
                "date": tx["date"],
                "type": tx_type_labels.get(tx["business_type"], tx["business_type"]),
                "amount": tx["amount"],
                "description": tx["description"],
            })
        self._tx_model.set_data(tx_data)

        # Balance sheet table
        bs_data = []
        for group in snapshot.account_groups:
            for acc in group["accounts"]:
                bs_data.append({
                    "group": group["group"],
                    "name": acc["name"],
                    "balance": acc["balance"],
                })
        for group in snapshot.liability_groups:
            for acc in group["accounts"]:
                bs_data.append({
                    "group": group["group"],
                    "name": acc["name"],
                    "balance": acc["balance"],
                })
        self._bs_model.set_data(bs_data)
        self._bs_warning.setText(snapshot.investment_valuation_warning)

    def _on_chart_clicked(self, params_json: str) -> None:
        """When a chart element is clicked, offer to navigate to filtered transactions."""
        import json
        try:
            params = json.loads(params_json)
        except json.JSONDecodeError:
            return

        # If it's a bar chart click on a month, we could filter
        month_name = params.get("name", "")
        if month_name and month_name != params.get("seriesName", ""):
            reply = QMessageBox.question(
                self, "钻取", f"是否查看 {month_name} 的明细流水？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                AppEventBus.instance().ledger_changed.emit()

    def _on_print_preview(self) -> None:
        """Open print preview dialog."""
        if not self._summary:
            QMessageBox.information(self, "提示", "请先查询报表数据")
            return

        headers = ["日期", "类型", "金额", "备注"]
        type_labels = {
            "income": "收入", "expense": "支出", "lend": "垫付", "recover": "收回",
            "stock_profit": "投资盈利", "stock_loss": "投资亏损",
        }
        rows = []
        for tx in self._summary.transaction_details:
            rows.append({
                "日期": tx["date"],
                "类型": type_labels.get(tx["business_type"], tx["business_type"]),
                "金额": tx["amount"],
                "备注": tx["description"],
            })

        dialog = PrintPreviewDialog(
            title="收支报表",
            headers=headers,
            rows=rows,
            ledger_name="MYM",
            page_size="A4",
            orientation="portrait",
            extra_meta=f"共 {len(rows)} 条记录",
            parent=self,
        )
        dialog.exec()

    def _on_export_csv(self) -> None:
        """Export report to CSV."""
        if not self._summary:
            QMessageBox.information(self, "提示", "请先查询报表数据")
            return

        headers = ["date", "type", "amount", "description"]
        type_labels = {
            "income": "收入", "expense": "支出", "lend": "垫付", "recover": "收回",
            "stock_profit": "投资盈利", "stock_loss": "投资亏损",
        }
        rows = []
        for tx in self._summary.transaction_details:
            rows.append({
                "date": tx["date"],
                "type": type_labels.get(tx["business_type"], tx["business_type"]),
                "amount": tx["amount"],
                "description": tx["description"],
            })

        ok, path, msg = ExportService.export_csv(rows, headers, prefix="report")
        QMessageBox.information(self, "导出结果", msg)

    def on_enter(self) -> None:
        self._on_query()

    def on_leave(self) -> None:
        pass
