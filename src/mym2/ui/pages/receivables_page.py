"""应收管理页面 — 垫付/还款跟踪。

功能：
- 待收列表：仍有未收回余额的债务人
- 历史：所有应收相关流水
- 债务人汇总：按债务人统计
- 新增垫付、部分/全部收回、删除、备注筛选

所有写操作经过 ReceivableService → LedgerService；
普通流水编辑器禁止将普通支出/收入写入应收账户。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QDate,
    QModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mym2.db.models.account import Account
from mym2.db.models.transaction import Transaction
from mym2.db.session import get_session
from mym2.domain.enums import TransactionType
from mym2.domain.money import Money
from mym2.services.balance_service import BalanceService
from mym2.services.ledger_service import LedgerService
from mym2.services.receivable_service import (
    AdvanceDTO,
    ReceivableService,
    ReceivableSummary,
    ReceivableTransactionView,
    RepayDTO,
)

logger = logging.getLogger("mym2.ui.receivables_page")

TYPE_LABELS: dict[str, str] = {
    TransactionType.RECEIVABLE_ADVANCE: "垫付",
    TransactionType.RECEIVABLE_REPAYMENT: "还款",
}

# ── Helper ────────────────────────────────────────────


def _format_minor(minor: int) -> str:
    return Money(minor=minor).format()


def _parse_date_text(text: str) -> QDate:
    try:
        dt = date.fromisoformat(text)
        return QDate(dt.year, dt.month, dt.day)
    except (ValueError, TypeError):
        return QDate.currentDate()


# ═══════════════════════════════════════════════════════
#  Table models
# ═══════════════════════════════════════════════════════


class TransactionViewModel(QAbstractTableModel):
    """应收流水表格模型。

    Columns: 日期, 类型, 债务人, 对方账户, 金额, 备注.
    """

    COLUMNS = ["日期", "类型", "债务人", "对方账户", "金额", "备注"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._views: list[ReceivableTransactionView] = []
        self._transactions: list[Transaction] = []

    def load_data(
        self,
        views: list[ReceivableTransactionView],
        transactions: list[Transaction],
    ) -> None:
        self.beginResetModel()
        self._views = views
        self._transactions = transactions
        self.endResetModel()

    def get_view(self, row: int) -> ReceivableTransactionView | None:
        if 0 <= row < len(self._views):
            return self._views[row]
        return None

    def get_transaction(self, row: int) -> Transaction | None:
        if 0 <= row < len(self._transactions):
            return self._transactions[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._views)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        v = self._views[row]

        if role == Qt.DisplayRole:
            cols = [
                str(v.transaction_date),
                TYPE_LABELS.get(v.transaction_type, v.transaction_type),
                v.debtor_account_name,
                v.counter_account_name or "",
                _format_minor(v.amount_minor),
                v.note or "",
            ]
            return cols[col]

        if role == Qt.TextAlignmentRole and col == 4:
            return Qt.AlignRight | Qt.AlignVCenter

        return None


class DebtorSummaryModel(QAbstractTableModel):
    """债务人汇总表格模型。

    Columns: 债务人, 待收余额, 累计垫付, 累计还款, 待收笔数.
    """

    COLUMNS = ["债务人", "待收余额", "累计垫付", "累计还款", "垫付笔数"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._summaries: list[ReceivableSummary] = []

    def load_data(self, summaries: list[ReceivableSummary]) -> None:
        self.beginResetModel()
        self._summaries = summaries
        self.endResetModel()

    def get_summary(self, row: int) -> ReceivableSummary | None:
        if 0 <= row < len(self._summaries):
            return self._summaries[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._summaries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        s = self._summaries[row]

        if role == Qt.DisplayRole:
            cols = [
                s.account_name,
                _format_minor(s.balance_minor),
                _format_minor(s.total_advanced_minor),
                _format_minor(s.total_repaid_minor),
                str(s.pending_count),
            ]
            return cols[col]

        if role == Qt.TextAlignmentRole and col in (1, 2, 3, 4):
            return Qt.AlignRight | Qt.AlignVCenter

        # Background color for outstanding balance
        if role == Qt.BackgroundRole and col == 1 and s.balance_minor > 0:
                from PySide6.QtGui import QColor
                return QColor(255, 240, 230)  # light orange

        return None


# ═══════════════════════════════════════════════════════
#  Dialogs
# ═══════════════════════════════════════════════════════


class AdvanceDialog(QDialog):
    """新增垫付对话框。"""

    def __init__(
        self,
        service: ReceivableService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("新增垫付")
        self.setMinimumWidth(420)
        self._setup_ui()
        self._load_accounts()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        self._debtor_combo = QComboBox()
        layout.addRow("债务人：", self._debtor_combo)

        self._funding_combo = QComboBox()
        layout.addRow("资金来源：", self._funding_combo)

        self._amount_edit = QLineEdit()
        self._amount_edit.setPlaceholderText("请输入金额（元）")
        layout.addRow("金额（元）：", self._amount_edit)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        layout.addRow("日期：", self._date_edit)

        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("备注（可选）")
        layout.addRow("备注：", self._note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _load_accounts(self) -> None:
        sess = get_session()
        try:
            debtors = self._service.get_receivable_accounts(sess)
            self._debtor_combo.clear()
            for acct in debtors:
                balance = _format_minor(acct.current_balance_minor)
                self._debtor_combo.addItem(
                    f"{acct.name}  (待收 {balance})", acct.id
                )

            funders = self._service.get_non_receivable_asset_accounts(sess)
            self._funding_combo.clear()
            for acct in funders:
                balance = _format_minor(acct.current_balance_minor)
                self._funding_combo.addItem(
                    f"{acct.name}  (余额 {balance})", acct.id
                )
        finally:
            sess.close()

    def _on_accept(self) -> None:
        debtor_id = self._debtor_combo.currentData()
        funding_id = self._funding_combo.currentData()
        amount_text = self._amount_edit.text().strip()

        if not debtor_id or not funding_id:
            QMessageBox.warning(self, "验证失败", "请选择债务人和资金来源账户。")
            return

        if not amount_text:
            QMessageBox.warning(self, "验证失败", "请输入金额。")
            return

        try:
            amount_yuan = float(amount_text)
            if amount_yuan <= 0:
                raise ValueError("金额必须为正")
            amount_minor = round(amount_yuan * 100)
        except (ValueError, TypeError):
            QMessageBox.warning(self, "验证失败", "请输入有效的正数金额。")
            return

        qdate = self._date_edit.date()
        tx_date = date(qdate.year(), qdate.month(), qdate.day())
        note = self._note_edit.text().strip() or None

        sess = get_session()
        try:
            dto = AdvanceDTO(
                debtor_account_id=debtor_id,
                funding_account_id=funding_id,
                amount_minor=amount_minor,
                transaction_date=tx_date,
                note=note,
            )
            self._service.advance(sess, dto)
            sess.commit()
            self.accept()
        except ValueError as e:
            sess.rollback()
            QMessageBox.warning(self, "操作失败", str(e))
        except Exception:
            sess.rollback()
            logger.exception("垫付操作异常")
            QMessageBox.critical(self, "错误", "操作失败，请重试。")
        finally:
            sess.close()


class RepayDialog(QDialog):
    """收回欠款对话框（支持部分/全部）。"""

    def __init__(
        self,
        service: ReceivableService,
        debtor_account: Account | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._prefill_debtor = debtor_account
        self.setWindowTitle("收回欠款")
        self.setMinimumWidth(420)
        self._setup_ui()
        self._load_accounts()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        self._debtor_combo = QComboBox()
        self._debtor_combo.currentIndexChanged.connect(self._on_debtor_changed)
        layout.addRow("债务人：", self._debtor_combo)

        self._balance_label = QLabel("")
        self._balance_label.setStyleSheet("color: #e88; font-weight: bold;")
        layout.addRow("待收余额：", self._balance_label)

        self._collection_combo = QComboBox()
        layout.addRow("收款账户：", self._collection_combo)

        self._amount_edit = QLineEdit()
        self._amount_edit.setPlaceholderText("请输入还款金额（元），留空=全部收回")
        layout.addRow("金额（元）：", self._amount_edit)

        self._full_check = QCheckBox("全部收回")
        self._full_check.toggled.connect(self._on_full_toggled)
        layout.addRow("", self._full_check)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        layout.addRow("日期：", self._date_edit)

        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("备注（可选）")
        layout.addRow("备注：", self._note_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _load_accounts(self) -> None:
        sess = get_session()
        try:
            debtors = self._service.get_receivable_accounts(sess)
            self._debtor_combo.clear()
            selected_idx = -1
            for i, acct in enumerate(debtors):
                balance = _format_minor(acct.current_balance_minor)
                self._debtor_combo.addItem(
                    f"{acct.name}  (待收 {balance})", acct.id
                )
                if self._prefill_debtor and acct.id == self._prefill_debtor.id:
                    selected_idx = i
            if selected_idx >= 0:
                self._debtor_combo.setCurrentIndex(selected_idx)

            collectors = self._service.get_non_receivable_asset_accounts(sess)
            self._collection_combo.clear()
            for acct in collectors:
                balance = _format_minor(acct.current_balance_minor)
                self._collection_combo.addItem(
                    f"{acct.name}  (余额 {balance})", acct.id
                )
        finally:
            sess.close()

    def _on_debtor_changed(self, index: int) -> None:
        if index < 0:
            return
        debtor_id = self._debtor_combo.currentData()
        if not debtor_id:
            return
        sess = get_session()
        try:
            balance = self._service.get_receivable_balance(sess, debtor_id)
            self._balance_label.setText(_format_minor(balance))
        finally:
            sess.close()

    def _on_full_toggled(self, checked: bool) -> None:
        self._amount_edit.setEnabled(not checked)
        if checked:
            self._amount_edit.clear()
            self._amount_edit.setPlaceholderText("将全部收回待收余额")

    def _on_accept(self) -> None:
        debtor_id = self._debtor_combo.currentData()
        collection_id = self._collection_combo.currentData()

        if not debtor_id or not collection_id:
            QMessageBox.warning(self, "验证失败", "请选择债务人和收款账户。")
            return

        sess = get_session()
        try:
            balance = self._service.get_receivable_balance(sess, debtor_id)
        finally:
            sess.close()

        if self._full_check.isChecked():
            amount_minor = balance
            if amount_minor <= 0:
                QMessageBox.information(self, "提示", "该债务人已无待收余额。")
                return
        else:
            amount_text = self._amount_edit.text().strip()
            if not amount_text:
                QMessageBox.warning(self, "验证失败", "请输入金额。")
                return
            try:
                amount_yuan = float(amount_text)
                if amount_yuan <= 0:
                    raise ValueError("金额必须为正")
                amount_minor = round(amount_yuan * 100)
            except (ValueError, TypeError):
                QMessageBox.warning(self, "验证失败", "请输入有效的正数金额。")
                return

            if amount_minor > balance:
                QMessageBox.warning(
                    self,
                    "验证失败",
                    f"还款金额 ({_format_minor(amount_minor)}) "
                    f"超过当前待收余额 ({_format_minor(balance)})",
                )
                return

        qdate = self._date_edit.date()
        tx_date = date(qdate.year(), qdate.month(), qdate.day())
        note = self._note_edit.text().strip() or None

        sess = get_session()
        try:
            dto = RepayDTO(
                debtor_account_id=debtor_id,
                collection_account_id=collection_id,
                amount_minor=amount_minor,
                transaction_date=tx_date,
                note=note,
            )
            self._service.repay(sess, dto)
            sess.commit()
            self.accept()
        except ValueError as e:
            sess.rollback()
            QMessageBox.warning(self, "操作失败", str(e))
        except Exception:
            sess.rollback()
            logger.exception("还款操作异常")
            QMessageBox.critical(self, "错误", "操作失败，请重试。")
        finally:
            sess.close()


# ═══════════════════════════════════════════════════════
#  Main page
# ═══════════════════════════════════════════════════════


class ReceivablesPage(QWidget):
    """应收管理页面。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = ReceivableService()
        self._balance = BalanceService()
        self._ledger = LedgerService()

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── 标题栏 + 操作按钮 ──
        header = QHBoxLayout()
        title = QLabel("应收管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #eee;")
        header.addWidget(title)
        header.addStretch()

        self._advance_btn = QPushButton("＋ 新增垫付")
        self._advance_btn.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: #fff; padding: 6px 16px; "
            "border-radius: 4px; font-size: 13px; } "
            "QPushButton:hover { background: #5b7dff; }"
        )
        self._advance_btn.clicked.connect(self._on_advance)
        header.addWidget(self._advance_btn)

        self._repay_btn = QPushButton("↩ 收回欠款")
        self._repay_btn.setStyleSheet(
            "QPushButton { background: #38a169; color: #fff; padding: 6px 16px; "
            "border-radius: 4px; font-size: 13px; } "
            "QPushButton:hover { background: #48bb78; }"
        )
        self._repay_btn.clicked.connect(self._on_repay)
        header.addWidget(self._repay_btn)

        root.addLayout(header)

        # ── Tab 页签 ──
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        # Tab 1: 待收列表
        self._pending_table = QTableView()
        self._pending_model = TransactionViewModel(self)
        self._pending_table.setModel(self._pending_model)
        self._pending_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._pending_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._pending_table.setAlternatingRowColors(True)
        self._pending_table.horizontalHeader().setStretchLastSection(True)
        self._pending_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._pending_table.setStyleSheet(
            "QTableView { background: #252736; alternate-background-color: #2a2c3d; "
            "gridline-color: #3a3d50; } "
            "QTableView::item:selected { background: #4a6cf7; } "
            "QHeaderView::section { background: #2b2d3e; color: #aaa; "
            "padding: 4px 8px; border: none; }"
        )
        self._pending_table.doubleClicked.connect(
            lambda _: self._on_repay_for_selected()
        )
        self._tabs.addTab(self._pending_table, "待收列表")

        # Tab 2: 历史流水
        self._history_table = QTableView()
        self._history_model = TransactionViewModel(self)
        self._history_table.setModel(self._history_model)
        self._history_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._history_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._history_table.setAlternatingRowColors(True)
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._history_table.setStyleSheet(
            "QTableView { background: #252736; alternate-background-color: #2a2c3d; "
            "gridline-color: #3a3d50; } "
            "QTableView::item:selected { background: #4a6cf7; } "
            "QHeaderView::section { background: #2b2d3e; color: #aaa; "
            "padding: 4px 8px; border: none; }"
        )

        hist_toolbar = QHBoxLayout()

        self._hist_debtor_filter = QComboBox()
        self._hist_debtor_filter.addItem("全部债务人", None)
        hist_toolbar.addWidget(QLabel("债务人："))
        hist_toolbar.addWidget(self._hist_debtor_filter)

        hist_toolbar.addSpacing(16)

        self._hist_type_filter = QComboBox()
        self._hist_type_filter.addItem("全部类型", None)
        self._hist_type_filter.addItem("垫付", TransactionType.RECEIVABLE_ADVANCE)
        self._hist_type_filter.addItem("还款", TransactionType.RECEIVABLE_REPAYMENT)
        hist_toolbar.addWidget(QLabel("类型："))
        hist_toolbar.addWidget(self._hist_type_filter)

        hist_toolbar.addSpacing(16)

        self._hist_date_from = QDateEdit()
        self._hist_date_from.setCalendarPopup(True)
        self._hist_date_from.setDate(QDate.currentDate().addMonths(-12))
        self._hist_date_from.setDisplayFormat("yyyy-MM-dd")
        hist_toolbar.addWidget(QLabel("从："))
        hist_toolbar.addWidget(self._hist_date_from)

        self._hist_date_to = QDateEdit()
        self._hist_date_to.setCalendarPopup(True)
        self._hist_date_to.setDate(QDate.currentDate())
        self._hist_date_to.setDisplayFormat("yyyy-MM-dd")
        hist_toolbar.addWidget(QLabel("到："))
        hist_toolbar.addWidget(self._hist_date_to)

        self._hist_search_btn = QPushButton("查询")
        self._hist_search_btn.clicked.connect(self._load_history)
        hist_toolbar.addWidget(self._hist_search_btn)

        hist_toolbar.addStretch()

        hist_layout = QVBoxLayout()
        hist_layout.addLayout(hist_toolbar)
        hist_layout.addWidget(self._history_table)

        hist_container = QWidget()
        hist_container.setLayout(hist_layout)
        self._tabs.addTab(hist_container, "历史流水")

        # Tab 3: 债务人汇总
        self._summary_table = QTableView()
        self._summary_model = DebtorSummaryModel(self)
        self._summary_table.setModel(self._summary_model)
        self._summary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._summary_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._summary_table.setAlternatingRowColors(True)
        self._summary_table.horizontalHeader().setStretchLastSection(True)
        self._summary_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._summary_table.setStyleSheet(
            "QTableView { background: #252736; alternate-background-color: #2a2c3d; "
            "gridline-color: #3a3d50; } "
            "QTableView::item:selected { background: #4a6cf7; } "
            "QHeaderView::section { background: #2b2d3e; color: #aaa; "
            "padding: 4px 8px; border: none; }"
        )
        self._summary_table.doubleClicked.connect(
            lambda _: self._on_repay_for_selected()
        )
        self._tabs.addTab(self._summary_table, "债务人汇总")

        # ── 底部操作栏 ──
        footer = QHBoxLayout()
        footer.addStretch()

        self._delete_btn = QPushButton("删除选中流水")
        self._delete_btn.setStyleSheet(
            "QPushButton { background: #e53e3e; color: #fff; padding: 6px 16px; "
            "border-radius: 4px; font-size: 13px; } "
            "QPushButton:hover { background: #fc8181; }"
        )
        self._delete_btn.clicked.connect(self._on_delete)
        footer.addWidget(self._delete_btn)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setStyleSheet(
            "QPushButton { background: #4a5568; color: #fff; padding: 6px 16px; "
            "border-radius: 4px; font-size: 13px; } "
            "QPushButton:hover { background: #718096; }"
        )
        self._refresh_btn.clicked.connect(self.refresh_all)
        footer.addWidget(self._refresh_btn)

        root.addLayout(footer)

        # 初始加载
        self.refresh_all()

    def refresh_all(self) -> None:
        """刷新所有标签页数据。"""
        self._load_pending()
        self._load_summary()
        self._load_history()
        self._refresh_debtor_filters()

    def _refresh_debtor_filters(self) -> None:
        sess = get_session()
        try:
            debtors = self._service.get_receivable_accounts(sess)
            current = self._hist_debtor_filter.currentData()
            self._hist_debtor_filter.clear()
            self._hist_debtor_filter.addItem("全部债务人", None)
            idx = 0
            for i, acct in enumerate(debtors):
                self._hist_debtor_filter.addItem(acct.name, acct.id)
                if acct.id == current:
                    idx = i + 1
            self._hist_debtor_filter.setCurrentIndex(idx)
        finally:
            sess.close()

    def _load_pending(self) -> None:
        """加载待收列表。"""
        sess = get_session()
        try:
            all_txs = self._service.get_receivable_transactions(sess)
            views = self._service.build_transaction_views(sess, all_txs)

            # 筛选：只显示债务人待收余额 > 0 的条目
            debtor_balances: dict[str, int] = {}
            for acct in self._service.get_receivable_accounts(sess):
                debtor_balances[acct.id] = acct.current_balance_minor

            pending_views = [
                v for v in views
                if debtor_balances.get(v.debtor_account_id, 0) > 0
            ]

            # 获取对应的 Transaction 列表
            tx_map = {t.id: t for t in all_txs}
            pending_txs = [
                tx_map[v.transaction_id]
                for v in pending_views
                if v.transaction_id in tx_map
            ]

            self._pending_model.load_data(pending_views, pending_txs)
        finally:
            sess.close()

    def _load_history(self) -> None:
        """加载历史流水。"""
        sess = get_session()
        try:
            debtor_id = self._hist_debtor_filter.currentData()
            type_filter = self._hist_type_filter.currentData()

            d_from = self._hist_date_from.date()
            d_to = self._hist_date_to.date()
            date_from = (
                date(d_from.year(), d_from.month(), d_from.day())
                if d_from.isValid() else None
            )
            date_to = (
                date(d_to.year(), d_to.month(), d_to.day())
                if d_to.isValid() else None
            )

            all_txs = self._service.get_receivable_transactions(
                sess,
                account_id=debtor_id,
                type_filter=type_filter,
                date_from=date_from,
                date_to=date_to,
            )
            views = self._service.build_transaction_views(sess, all_txs)
            self._history_model.load_data(views, all_txs)
        finally:
            sess.close()

    def _load_summary(self) -> None:
        """加载债务人汇总。"""
        sess = get_session()
        try:
            summaries = self._service.get_all_receivable_summaries(sess)
            self._summary_model.load_data(summaries)
        finally:
            sess.close()

    def _on_advance(self) -> None:
        """打开新增垫付对话框。"""
        dlg = AdvanceDialog(self._service, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_all()

    def _on_repay(self) -> None:
        """打开收回欠款对话框。"""
        dlg = RepayDialog(self._service, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_all()

    def _on_repay_for_selected(self) -> None:
        """对选中债务人快速还款。"""
        current_tab = self._tabs.currentIndex()

        if current_tab == 0:  # 待收列表
            idx = self._pending_table.currentIndex().row()
            view = self._pending_model.get_view(idx)
        elif current_tab == 2:  # 债务人汇总
            idx = self._summary_table.currentIndex().row()
            summary = self._summary_model.get_summary(idx)
            if summary is None:
                return
            sess = get_session()
            try:
                acct = sess.get(Account, summary.account_id)
            finally:
                sess.close()
            dlg = RepayDialog(self._service, debtor_account=acct, parent=self)
            if dlg.exec() == QDialog.Accepted:
                self.refresh_all()
            return
        else:
            return

        if view is None:
            return

        sess = get_session()
        try:
            acct = sess.get(Account, view.debtor_account_id)
        finally:
            sess.close()

        if acct and acct.current_balance_minor > 0:
            dlg = RepayDialog(self._service, debtor_account=acct, parent=self)
            if dlg.exec() == QDialog.Accepted:
                self.refresh_all()

    def _on_delete(self) -> None:
        """删除选中流水。"""
        current_tab = self._tabs.currentIndex()

        if current_tab == 0:  # 待收
            idx = self._pending_table.currentIndex().row()
            view = self._pending_model.get_view(idx)
        elif current_tab == 1:  # 历史
            idx = self._history_table.currentIndex().row()
            view = self._history_model.get_view(idx)
        else:
            return

        if view is None:
            QMessageBox.information(self, "提示", "请先选择一条流水。")
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除 {TYPE_LABELS.get(view.transaction_type, view.transaction_type)} "
            f"记录吗？\n金额：{_format_minor(view.amount_minor)}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        sess = get_session()
        try:
            self._service.delete_receivable_transaction(
                sess, view.transaction_id
            )
            sess.commit()
            self.refresh_all()
        except ValueError as e:
            sess.rollback()
            QMessageBox.warning(self, "操作失败", str(e))
        except Exception:
            sess.rollback()
            logger.exception("删除流水异常")
            QMessageBox.critical(self, "错误", "操作失败，请重试。")
        finally:
            sess.close()
