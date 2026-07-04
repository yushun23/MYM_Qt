"""流水管理页面 — QTableView + 筛选 + CRUD + 导出。

支持日期范围、账户、分类、类型、关键词、清算状态筛选；
稳定排序（同日按创建时间）；分页。
支出/收入/转账三种普通新增对话框；
应收、余额调节、历史结算不出现在普通新增菜单。
编辑/删除必须确认，写操作只调用 LedgerService。
锁定历史结算流水只读并标注"历史导入"。
导出遵从当前筛选条件，CSV/Excel 对公式注入防护。
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QDate,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QAction, QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.db.session import get_session
from mym2.domain.enums import TransactionType
from mym2.repositories.transaction_repo import TransactionFilter, TransactionRepository
from mym2.services.balance_service import BalanceService
from mym2.services.dto import CreateTransactionDTO, UpdateTransactionDTO
from mym2.services.ledger_service import LedgerService

logger = logging.getLogger("mym2.ui.transactions_page")

TX_TYPE_LABELS: dict[str, str] = {
    "expense": "支出",
    "income": "收入",
    "transfer": "转账",
    "receivable_advance": "应收垫付",
    "receivable_repayment": "应收还款",
    "balance_adjustment": "余额调节",
    "historical_investment_settlement": "历史投资结算",
}

# 普通新增菜单允许的类型
REGULAR_TYPES: list[str] = ["expense", "income", "transfer"]

PAGE_SIZES = [20, 50, 100, 200]

# ── 公式注入防护前缀 ──
_FORMULA_TRIGGERS = frozenset({"=", "+", "-", "@"})


def _minor_to_yuan(minor: int) -> str:
    """整数分 → 元显示（保留两位小数）。"""
    sign = "-" if minor < 0 else ""
    val = abs(minor)
    yuan = val // 100
    fen = val % 100
    return f"{sign}{yuan}.{fen:02d}"


def _protect_cell(value: str) -> str:
    """对以 = + - @ 开头的文本做公式注入防护。

    策略：在前面加单引号 ' 前缀（CSV/Excel 通用手法）。
    """
    if value and value[0] in _FORMULA_TRIGGERS:
        return f"'{value}"
    return value


def _parse_date_text(text: str) -> QDate:
    """解析 ISO 日期字符串为 QDate。"""
    try:
        dt = date.fromisoformat(text)
        return QDate(dt.year, dt.month, dt.day)
    except (ValueError, TypeError):
        return QDate.currentDate()


class TransactionTableModel(QAbstractTableModel):
    """流水表格数据模型。

    Columns: 日期, 类型, 来源账户, 目标账户, 分类, 金额, 备注, 清算, 状态.
    """

    COLUMNS = ["日期", "类型", "来源账户", "目标账户", "分类", "金额", "备注", "清算", "状态"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._raw_transactions: list[Transaction] = []
        self._accounts: dict[str, Account] = {}
        self._categories: dict[str, Category] = {}

    def set_lookups(
        self,
        accounts: dict[str, Account],
        categories: dict[str, Category],
    ) -> None:
        self._accounts = accounts
        self._categories = categories

    def load_data(self, transactions: list[Transaction]) -> None:
        self.beginResetModel()
        self._raw_transactions = transactions
        self._rows = []
        for tx in transactions:
            cat = self._categories.get(tx.category_id) if tx.category_id else None
            acct_out = self._accounts.get(tx.account_out_id)
            acct_in = self._accounts.get(tx.account_in_id) if tx.account_in_id else None

            # 状态文本
            if tx.is_locked:
                status = "历史导入"
            elif tx.source == "import":
                status = "导入"
            elif tx.source == "ai":
                status = "AI"
            else:
                status = ""

            self._rows.append({
                "id": tx.id,
                "transaction_date": str(tx.transaction_date),
                "type": tx.type,
                "type_label": TX_TYPE_LABELS.get(tx.type, tx.type),
                "account_out_name": acct_out.name if acct_out else tx.account_out_id,
                "account_in_name": acct_in.name if acct_in else "",
                "category_name": cat.name if cat else "",
                "amount_minor": tx.amount_minor,
                "amount_display": _minor_to_yuan(tx.amount_minor),
                "note": tx.note or "",
                "is_cleared": tx.is_cleared,
                "is_locked": tx.is_locked,
                "source": tx.source or "manual",
                "status": status,
            })
        self.endResetModel()

    def get_transaction(self, row: int) -> Transaction | None:
        if 0 <= row < len(self._raw_transactions):
            return self._raw_transactions[row]
        return None

    def get_tx_data(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        item = self._rows[row]

        if role == Qt.DisplayRole:
            if col == 0:
                return item["transaction_date"]
            elif col == 1:
                return item["type_label"]
            elif col == 2:
                return item["account_out_name"]
            elif col == 3:
                return item["account_in_name"]
            elif col == 4:
                return item["category_name"]
            elif col == 5:
                return item["amount_display"]
            elif col == 6:
                return item["note"]
            elif col == 7:
                return "✓" if item["is_cleared"] else ""
            elif col == 8:
                return item["status"]

        elif role == Qt.TextAlignmentRole:
            if col == 5:
                return Qt.AlignRight | Qt.AlignVCenter
            if col == 7:
                return Qt.AlignCenter

        elif role == Qt.ForegroundRole:
            if col == 5 and item["type"] == "expense":
                return QColor("#e06c75")
            elif col == 5 and item["type"] == "income":
                return QColor("#98c379")
            if item["is_locked"]:
                return QColor("#888888")

        elif role == Qt.ToolTipRole:
            if col == 1:
                return item["type_label"]
            elif col == 6:
                return item["note"]
            elif col == 8:
                return item["status"]

        return None


# ── 新增/编辑对话框 ──────────────────────────────────


class TransactionEditDialog(QDialog):
    """支出/收入/转账新增与编辑对话框。

    金额控件：QLineEdit + QDoubleValidator(0, 999999999.99, 2)。
    日期：QDateEdit。
    """

    def __init__(
        self,
        parent: QWidget | None,
        tx_type: str,
        accounts: list[Account],
        categories: list[Category],
        existing: Transaction | None = None,
    ) -> None:
        super().__init__(parent)
        self._tx_type = tx_type
        self._accounts = {a.id: a for a in accounts}
        self._categories = {c.id: c for c in categories}
        self._existing = existing
        self._result_dto: CreateTransactionDTO | UpdateTransactionDTO | None = None
        self._result_type: str = tx_type

        type_label = TX_TYPE_LABELS.get(tx_type, tx_type)
        is_edit = existing is not None
        title = f"{'编辑' if is_edit else '新增'}{type_label}"
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        self._build_ui()
        if existing:
            self._populate_existing(existing)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        # 日期
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.setDate(QDate.currentDate())
        form.addRow("日期:", self._date_edit)

        # 来源账户
        self._account_out_combo = QComboBox()
        self._account_out_combo.setMinimumWidth(200)
        enabled_accounts = [
            a for a in self._accounts.values()
            if a.is_enabled and a.is_editable and not a.is_locked
        ]
        for a in enabled_accounts:
            self._account_out_combo.addItem(f"{a.name}", a.id)
        form.addRow("来源账户:", self._account_out_combo)

        # 目标账户（仅转账需要）
        self._account_in_combo: QComboBox | None = None
        if self._tx_type == "transfer":
            self._account_in_combo = QComboBox()
            self._account_in_combo.setMinimumWidth(200)
            for a in enabled_accounts:
                self._account_in_combo.addItem(f"{a.name}", a.id)
            form.addRow("目标账户:", self._account_in_combo)

        # 分类（支出/收入需要）
        self._category_combo: QComboBox | None = None
        if self._tx_type in ("expense", "income"):
            self._category_combo = QComboBox()
            self._category_combo.setMinimumWidth(200)
            cat_type = "expense" if self._tx_type == "expense" else "income"
            matching_categories = [
                c for c in self._categories.values()
                if c.type == cat_type and c.is_enabled
            ]
            for c in matching_categories:
                self._category_combo.addItem(f"{c.name}", c.id)
            form.addRow("分类:", self._category_combo)

        # 金额
        self._amount_edit = QLineEdit()
        self._amount_edit.setPlaceholderText("0.00")
        # 最多两位小数，范围 0.01 ~ 999,999,999.99
        validator = QDoubleValidator(0.01, 999_999_999.99, 2)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self._amount_edit.setValidator(validator)
        form.addRow("金额:", self._amount_edit)

        # 备注
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("选填")
        form.addRow("备注:", self._note_edit)

        # 清算（仅编辑时显示）
        self._cleared_check: QCheckBox | None = None
        if self._existing is not None:
            self._cleared_check = QCheckBox("已清算")
            form.addRow("清算:", self._cleared_check)

        layout.addLayout(form)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_existing(self, tx: Transaction) -> None:
        self._date_edit.setDate(_parse_date_text(tx.transaction_date))
        self._amount_edit.setText(f"{tx.amount_minor / 100:.2f}")
        self._note_edit.setText(tx.note or "")

        # 账户预选
        idx = self._account_out_combo.findData(tx.account_out_id)
        if idx >= 0:
            self._account_out_combo.setCurrentIndex(idx)

        if self._account_in_combo and tx.account_in_id:
            idx = self._account_in_combo.findData(tx.account_in_id)
            if idx >= 0:
                self._account_in_combo.setCurrentIndex(idx)

        if self._category_combo and tx.category_id:
            idx = self._category_combo.findData(tx.category_id)
            if idx >= 0:
                self._category_combo.setCurrentIndex(idx)

        if self._cleared_check:
            self._cleared_check.setChecked(tx.is_cleared)

    def _on_accept(self) -> None:
        """验证并构建 DTO。"""
        amount_text = self._amount_edit.text().strip()
        if not amount_text:
            QMessageBox.warning(self, "验证失败", "请输入金额")
            return

        try:
            from decimal import Decimal
            amount_yuan = Decimal(amount_text)
            amount_minor = int((amount_yuan * 100).quantize(Decimal("1")))
        except Exception:
            QMessageBox.warning(self, "验证失败", f"无效金额: {amount_text}")
            return

        if amount_minor <= 0:
            QMessageBox.warning(self, "验证失败", "金额必须大于 0")
            return

        qdate = self._date_edit.date()
        tx_date = date(qdate.year(), qdate.month(), qdate.day())

        account_out_id = self._account_out_combo.currentData()
        if not account_out_id:
            QMessageBox.warning(self, "验证失败", "请选择来源账户")
            return

        account_in_id: str | None = None
        if self._account_in_combo:
            account_in_id = self._account_in_combo.currentData()
            if not account_in_id:
                QMessageBox.warning(self, "验证失败", "请选择目标账户")
                return

        category_id: str | None = None
        if self._category_combo:
            category_id = self._category_combo.currentData()

        if self._existing is not None:
            self._result_dto = UpdateTransactionDTO(
                transaction_date=tx_date,
                amount_minor=amount_minor,
                category_id=category_id,
                account_in_id=account_in_id,
                note=self._note_edit.text().strip() or None,
            )
        else:
            tx_type_enum = TransactionType(self._tx_type)
            self._result_dto = CreateTransactionDTO(
                transaction_type=tx_type_enum,
                transaction_date=tx_date,
                account_out_id=account_out_id,
                amount_minor=amount_minor,
                category_id=category_id,
                account_in_id=account_in_id,
                note=self._note_edit.text().strip() or None,
                source="manual",
            )

        self.accept()

    @property
    def result_dto(self) -> CreateTransactionDTO | UpdateTransactionDTO:
        return self._result_dto  # type: ignore[return-value]

    @property
    def result_type(self) -> str:
        return self._result_type


# ── 流水只读查看对话框（用于账户页跳转等） ──────────


class TransactionReadOnlyDialog(QDialog):
    """流水明细只读查看对话框。"""

    def __init__(
        self,
        parent: QWidget | None,
        account_name: str,
        rows: list[dict[str, Any]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{account_name} — 流水明细")
        self.resize(700, 400)

        layout = QVBoxLayout(self)

        table = QTableView()
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)

        class _ReadModel(QAbstractTableModel):
            COLS = ["日期", "类型", "金额", "分类", "备注", "对方账户"]

            def __init__(self, r: list[dict[str, Any]]):
                super().__init__()
                self._r = r

            def rowCount(self, parent=QModelIndex()):
                return len(self._r)

            def columnCount(self, parent=QModelIndex()):
                return len(self.COLS)

            def headerData(self, s, o, role=Qt.DisplayRole):
                if o == Qt.Horizontal and role == Qt.DisplayRole:
                    return self.COLS[s]
                return None

            def data(self, idx, role=Qt.DisplayRole):
                if not idx.isValid() or role != Qt.DisplayRole:
                    return None
                row = self._r[idx.row()]
                keys = ["date", "type", "amount", "category", "note", "counterparty"]
                return row.get(keys[idx.column()], "")

        model = _ReadModel(rows)
        table.setModel(model)
        layout.addWidget(table)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# ── 主页面 ──────────────────────────────────────


class TransactionsPage(QWidget):
    """流水管理主页面。"""

    CLEARED_ALL = "all"
    CLEARED_YES = "yes"
    CLEARED_NO = "no"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = LedgerService()
        self._balance_svc = BalanceService()
        self._current_page = 1
        self._page_size = 50
        self._total_count = 0
        self._sort_column = "transaction_date"
        self._sort_desc = True
        self._all_accounts: list[Account] = []
        self._all_categories: list[Category] = []

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── 标题栏 ──
        title_layout = QHBoxLayout()
        title = QLabel("流水管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # ── 筛选栏 ──
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)

        # 日期范围
        filter_layout.addWidget(QLabel("从:"))
        self._date_from_edit = QDateEdit()
        self._date_from_edit.setCalendarPopup(True)
        self._date_from_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_from_edit.setSpecialValueText("全部")
        self._date_from_edit.setDate(self._date_from_edit.minimumDate())
        filter_layout.addWidget(self._date_from_edit)

        filter_layout.addWidget(QLabel("到:"))
        self._date_to_edit = QDateEdit()
        self._date_to_edit.setCalendarPopup(True)
        self._date_to_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_to_edit.setDate(QDate.currentDate())
        filter_layout.addWidget(self._date_to_edit)

        # 账户筛选
        filter_layout.addWidget(QLabel("账户:"))
        self._account_filter = QComboBox()
        self._account_filter.setMinimumWidth(100)
        self._account_filter.addItem("全部", None)
        filter_layout.addWidget(self._account_filter)

        # 分类筛选
        filter_layout.addWidget(QLabel("分类:"))
        self._category_filter = QComboBox()
        self._category_filter.setMinimumWidth(100)
        self._category_filter.addItem("全部", None)
        filter_layout.addWidget(self._category_filter)

        # 类型筛选
        filter_layout.addWidget(QLabel("类型:"))
        self._type_filter = QComboBox()
        self._type_filter.setMinimumWidth(80)
        self._type_filter.addItem("全部", None)
        for t in ["expense", "income", "transfer"]:
            self._type_filter.addItem(TX_TYPE_LABELS.get(t, t), t)
        filter_layout.addWidget(self._type_filter)

        # 清算状态
        filter_layout.addWidget(QLabel("清算:"))
        self._cleared_filter = QComboBox()
        self._cleared_filter.addItem("全部", self.CLEARED_ALL)
        self._cleared_filter.addItem("已清算", self.CLEARED_YES)
        self._cleared_filter.addItem("未清算", self.CLEARED_NO)
        filter_layout.addWidget(self._cleared_filter)

        layout.addLayout(filter_layout)

        # ── 搜索 + 按钮栏 ──
        search_layout = QHBoxLayout()
        search_layout.setSpacing(6)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索备注或ID...")
        self._search_edit.setMinimumWidth(200)
        search_layout.addWidget(self._search_edit)

        self._search_btn = QPushButton("搜索")
        self._search_btn.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: #fff;"
            " padding: 6px 14px; border-radius: 4px; }"
            "QPushButton:hover { background: #5b7df8; }"
        )
        search_layout.addWidget(self._search_btn)

        self._clear_filter_btn = QPushButton("清除筛选")
        self._clear_filter_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; border-radius: 4px; }"
        )
        search_layout.addWidget(self._clear_filter_btn)

        search_layout.addStretch()

        # 新增按钮（仅普通类型）
        self._add_menu_btn = QPushButton("＋ 新增")
        self._add_menu_btn.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: #fff;"
            " padding: 6px 16px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #5b7df8; }"
        )
        search_layout.addWidget(self._add_menu_btn)

        self._add_menu = QMenu(self)
        for t in REGULAR_TYPES:
            action = QAction(TX_TYPE_LABELS.get(t, t), self)
            action.setData(t)
            action.triggered.connect(self._on_add_transaction)
            self._add_menu.addAction(action)
        self._add_menu_btn.setMenu(self._add_menu)

        self._edit_btn = QPushButton("编辑")
        self._edit_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; border-radius: 4px; }"
        )
        search_layout.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("删除")
        self._delete_btn.setStyleSheet(
            "QPushButton { color: #e06c75; padding: 6px 14px; border-radius: 4px; }"
        )
        search_layout.addWidget(self._delete_btn)

        self._export_btn = QPushButton("导出")
        self._export_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; border-radius: 4px; }"
        )
        search_layout.addWidget(self._export_btn)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; border-radius: 4px; }"
        )
        search_layout.addWidget(self._refresh_btn)

        layout.addLayout(search_layout)

        # ── 表格 ──
        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.verticalHeader().setVisible(False)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        self._model = TransactionTableModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._table.setModel(self._proxy)

        layout.addWidget(self._table, stretch=1)

        # ── 分页栏 ──
        page_layout = QHBoxLayout()
        page_layout.setSpacing(6)

        self._page_info_label = QLabel("共 0 条")
        page_layout.addWidget(self._page_info_label)

        page_layout.addStretch()

        page_layout.addWidget(QLabel("每页:"))
        self._page_size_combo = QComboBox()
        for ps in PAGE_SIZES:
            self._page_size_combo.addItem(str(ps), ps)
        self._page_size_combo.setCurrentText(str(self._page_size))
        page_layout.addWidget(self._page_size_combo)

        self._prev_btn = QPushButton("上一页")
        self._prev_btn.setStyleSheet("QPushButton { padding: 4px 10px; border-radius: 4px; }")
        page_layout.addWidget(self._prev_btn)

        self._page_label = QLabel(f"第 {self._current_page} 页")
        page_layout.addWidget(self._page_label)

        self._next_btn = QPushButton("下一页")
        self._next_btn.setStyleSheet("QPushButton { padding: 4px 10px; border-radius: 4px; }")
        page_layout.addWidget(self._next_btn)

        layout.addLayout(page_layout)

    def _connect_signals(self) -> None:
        self._search_btn.clicked.connect(self._on_search)
        self._search_edit.returnPressed.connect(self._on_search)
        self._clear_filter_btn.clicked.connect(self._on_clear_filters)
        self._edit_btn.clicked.connect(self._on_edit_transaction)
        self._delete_btn.clicked.connect(self._on_delete_transaction)
        self._export_btn.clicked.connect(self._on_export)
        self._refresh_btn.clicked.connect(self.refresh)
        self._prev_btn.clicked.connect(self._on_prev_page)
        self._next_btn.clicked.connect(self._on_next_page)
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)

        # 筛选栏变化时自动刷新
        self._date_from_edit.dateChanged.connect(self._on_search)
        self._date_to_edit.dateChanged.connect(self._on_search)
        self._account_filter.currentIndexChanged.connect(self._on_search)
        self._category_filter.currentIndexChanged.connect(self._on_search)
        self._type_filter.currentIndexChanged.connect(self._on_search)
        self._cleared_filter.currentIndexChanged.connect(self._on_search)

        # 双击编辑
        self._table.doubleClicked.connect(self._on_table_double_clicked)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """刷新表格数据。"""
        session = get_session()
        try:
            repo = TransactionRepository(session)

            # 加载 lookups
            self._all_accounts = list(repo.get_accounts_map().values())
            self._all_categories = list(repo.get_categories_map().values())

            # 更新筛选下拉
            self._update_filter_combos()

            # 查询
            f = self._build_filters()
            result = repo.query_filtered(
                f,
                page=self._current_page,
                page_size=self._page_size,
                sort_column=self._sort_column,
                sort_desc=self._sort_desc,
            )

            self._model.set_lookups(repo.get_accounts_map(), repo.get_categories_map())
            self._model.load_data(result.items)
            self._total_count = result.total

            self._update_pagination_info()

        finally:
            session.close()

    def _update_filter_combos(self) -> None:
        """更新账户和分类筛选下拉（保留当前选择）。"""
        current_account = self._account_filter.currentData()
        current_category = self._category_filter.currentData()

        self._account_filter.blockSignals(True)
        self._account_filter.clear()
        self._account_filter.addItem("全部", None)
        for a in self._all_accounts:
            self._account_filter.addItem(f"{a.name}", a.id)
        idx = self._account_filter.findData(current_account)
        if idx >= 0:
            self._account_filter.setCurrentIndex(idx)
        self._account_filter.blockSignals(False)

        self._category_filter.blockSignals(True)
        self._category_filter.clear()
        self._category_filter.addItem("全部", None)
        for c in self._all_categories:
            self._category_filter.addItem(f"{c.name}", c.id)
        idx = self._category_filter.findData(current_category)
        if idx >= 0:
            self._category_filter.setCurrentIndex(idx)
        self._category_filter.blockSignals(False)

    def _build_filters(self) -> TransactionFilter:
        """从当前 UI 构建筛选条件。"""
        f = TransactionFilter()

        # 日期范围
        d_from = self._date_from_edit.date()
        if d_from > self._date_from_edit.minimumDate():
            f.date_from = date(d_from.year(), d_from.month(), d_from.day())

        d_to = self._date_to_edit.date()
        if d_to < self._date_to_edit.maximumDate():
            f.date_to = date(d_to.year(), d_to.month(), d_to.day())

        # 账户
        acct_id = self._account_filter.currentData()
        if acct_id:
            f.account_ids = [acct_id]

        # 分类
        cat_id = self._category_filter.currentData()
        if cat_id:
            f.category_ids = [cat_id]

        # 类型
        tx_type = self._type_filter.currentData()
        if tx_type:
            f.types = [tx_type]

        # 关键词
        keyword = self._search_edit.text().strip()
        if keyword:
            f.keyword = keyword

        # 清算
        cleared_val = self._cleared_filter.currentData()
        if cleared_val == self.CLEARED_YES:
            f.is_cleared = True
        elif cleared_val == self.CLEARED_NO:
            f.is_cleared = False

        return f

    def _update_pagination_info(self) -> None:
        total_pages = max(1, (self._total_count + self._page_size - 1) // self._page_size)
        self._page_info_label.setText(f"共 {self._total_count} 条")
        self._page_label.setText(f"第 {min(self._current_page, total_pages)} / {total_pages} 页")
        self._prev_btn.setEnabled(self._current_page > 1)
        self._next_btn.setEnabled(self._current_page < total_pages)

    # ── 筛选/导航 ──

    def _on_search(self) -> None:
        self._current_page = 1
        self.refresh()

    def _on_clear_filters(self) -> None:
        self._date_from_edit.setDate(self._date_from_edit.minimumDate())
        self._date_to_edit.setDate(QDate.currentDate())
        self._account_filter.setCurrentIndex(0)
        self._category_filter.setCurrentIndex(0)
        self._type_filter.setCurrentIndex(0)
        self._cleared_filter.setCurrentIndex(0)
        self._search_edit.clear()
        self._on_search()

    def _on_prev_page(self) -> None:
        if self._current_page > 1:
            self._current_page -= 1
            self.refresh()

    def _on_next_page(self) -> None:
        total_pages = max(1, (self._total_count + self._page_size - 1) // self._page_size)
        if self._current_page < total_pages:
            self._current_page += 1
            self.refresh()

    def _on_page_size_changed(self) -> None:
        self._page_size = self._page_size_combo.currentData() or 50
        self._current_page = 1
        self.refresh()

    # ── 获取当前选中 ──

    def _get_selected_tx(self) -> Transaction | None:
        proxy_idx = self._table.currentIndex()
        if not proxy_idx.isValid():
            return None
        source_idx = self._proxy.mapToSource(proxy_idx)
        return self._model.get_transaction(source_idx.row())

    def _get_selected_row_data(self) -> dict[str, Any] | None:
        proxy_idx = self._table.currentIndex()
        if not proxy_idx.isValid():
            return None
        source_idx = self._proxy.mapToSource(proxy_idx)
        return self._model.get_tx_data(source_idx.row())

    # ── 右键菜单 ──

    def _on_context_menu(self, pos) -> None:
        menu = QMenu(self)
        edit_action = menu.addAction("编辑")
        delete_action = menu.addAction("删除")
        export_action = menu.addAction("导出")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == edit_action:
            self._on_edit_transaction()
        elif action == delete_action:
            self._on_delete_transaction()
        elif action == export_action:
            self._on_export()

    # ── 新增 ──

    def _on_add_transaction(self) -> None:
        action = self.sender()
        tx_type = action.data() if isinstance(action, QAction) else "expense"
        self._open_add_dialog(tx_type)

    def _open_add_dialog(self, tx_type: str) -> None:
        dlg = TransactionEditDialog(
            self,
            tx_type,
            self._all_accounts,
            self._all_categories,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        dto = dlg.result_dto
        if not isinstance(dto, CreateTransactionDTO):
            return

        try:
            session = get_session()
            try:
                with session.begin():
                    self._service.create_transaction(session, dto)
            finally:
                session.close()
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(self, "新增失败", str(e))

    # ── 编辑 ──

    def _on_table_double_clicked(self, index) -> None:
        self._on_edit_transaction()

    def _on_edit_transaction(self) -> None:
        tx = self._get_selected_tx()
        if tx is None:
            QMessageBox.information(self, "提示", "请先选择一条流水")
            return

        # 锁定检查
        if tx.is_locked:
            QMessageBox.warning(self, "无法编辑", "该流水已锁定（历史导入），不可编辑。")
            return
        if tx.type == TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT:
            QMessageBox.warning(self, "无法编辑", "历史投资结算流水不可编辑。")
            return

        # 确定编辑时使用的类型（仅允许 expense/income/transfer）
        if tx.type not in REGULAR_TYPES:
            QMessageBox.warning(
                self, "无法编辑",
                f"类型 \"{TX_TYPE_LABELS.get(tx.type, tx.type)}\" 不支持通过普通对话框编辑。"
            )
            return

        dlg = TransactionEditDialog(
            self,
            tx.type,
            self._all_accounts,
            self._all_categories,
            existing=tx,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        dto = dlg.result_dto
        if not isinstance(dto, UpdateTransactionDTO):
            return

        reply = QMessageBox.question(
            self,
            "确认编辑",
            "确定要保存修改吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            session = get_session()
            try:
                with session.begin():
                    self._service.update_transaction(session, tx.id, dto)
            finally:
                session.close()
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(self, "编辑失败", str(e))

    # ── 删除 ──

    def _on_delete_transaction(self) -> None:
        tx = self._get_selected_tx()
        if tx is None:
            QMessageBox.information(self, "提示", "请先选择一条流水")
            return

        if tx.is_locked:
            QMessageBox.warning(self, "无法删除", "该流水已锁定（历史导入），不可删除。")
            return
        if tx.type == TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT:
            QMessageBox.warning(self, "无法删除", "历史投资结算流水不可删除。")
            return

        row_data = self._get_selected_row_data()
        info = ""
        if row_data:
            info = (
                f"日期: {row_data['transaction_date']}\n"
                f"类型: {row_data['type_label']}\n"
                f"金额: {row_data['amount_display']}\n"
                f"备注: {row_data['note']}"
            )

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除以下流水吗？\n\n{info}\n\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            session = get_session()
            try:
                with session.begin():
                    self._service.delete_transaction(session, tx.id)
            finally:
                session.close()
            self.refresh()
        except ValueError as e:
            QMessageBox.warning(self, "删除失败", str(e))

    # ── 导出 ──

    def _on_export(self) -> None:
        """按当前筛选条件导出 CSV。"""
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出流水",
            "transactions.csv",
            "CSV 文件 (*.csv);;Excel 文件 (*.xlsx)",
        )
        if not path:
            return

        try:
            self._do_export_csv(path)
            QMessageBox.information(self, "导出完成", f"已导出到:\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _do_export_csv(self, path: str) -> None:
        """导出当前筛选条件的全部数据为 CSV。

        公式注入防护：对以 = + - @ 开头的文本字段加 ' 前缀。
        """
        session = get_session()
        try:
            repo = TransactionRepository(session)
            f = self._build_filters()
            result = repo.query_filtered(
                f,
                page=1,
                page_size=max(self._total_count, 10000),
                sort_column=self._sort_column,
                sort_desc=self._sort_desc,
            )

            accounts = repo.get_accounts_map()
            categories = repo.get_categories_map()

            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                headers = [
                    "日期", "类型", "来源账户", "目标账户", "分类",
                    "金额", "备注", "已清算", "锁定", "来源",
                ]
                writer.writerow(headers)

                for tx in result.items:
                    acct_out = accounts.get(tx.account_out_id)
                    acct_in = accounts.get(tx.account_in_id) if tx.account_in_id else None
                    cat = categories.get(tx.category_id) if tx.category_id else None

                    note = _protect_cell(tx.note or "")

                    writer.writerow([
                        str(tx.transaction_date),
                        TX_TYPE_LABELS.get(tx.type, tx.type),
                        acct_out.name if acct_out else tx.account_out_id,
                        acct_in.name if acct_in else "",
                        cat.name if cat else "",
                        _minor_to_yuan(tx.amount_minor),
                        note,
                        "是" if tx.is_cleared else "否",
                        "是" if tx.is_locked else "否",
                        tx.source or "manual",
                    ])

        finally:
            session.close()

    def navigate_to_transactions_for_account(self, account_id: str, account_name: str) -> None:
        """查看指定账户的流水（只读）。"""
        session = get_session()
        try:
            txs = session.execute(
                __import__("sqlalchemy").select(Transaction).where(
                    (Transaction.account_out_id == account_id)
                    | (Transaction.account_in_id == account_id)
                ).order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            ).scalars().all()

            cat_map: dict[str, Category] = {}
            acct_map: dict[str, Account] = {}
            for tx in txs:
                if tx.category_id and tx.category_id not in cat_map and tx.category:
                    cat_map[tx.category_id] = tx.category
                if tx.account_in_id and tx.account_in_id not in acct_map and tx.account_in:
                    acct_map[tx.account_in_id] = tx.account_in
                if tx.account_out_id and tx.account_out_id not in acct_map and tx.account_out:
                    acct_map[tx.account_out_id] = tx.account_out

            rows = []
            for tx in txs:
                cat = cat_map.get(tx.category_id)
                counterparty = ""
                if tx.account_out_id != account_id:
                    a = acct_map.get(tx.account_out_id)
                    counterparty = a.name if a else tx.account_out_id
                elif tx.account_in_id != account_id:
                    a = acct_map.get(tx.account_in_id)
                    counterparty = a.name if a else tx.account_in_id

                rows.append({
                    "date": str(tx.transaction_date),
                    "type": TX_TYPE_LABELS.get(tx.type, tx.type),
                    "amount": _minor_to_yuan(tx.amount_minor),
                    "category": cat.name if cat else "",
                    "note": tx.note or "",
                    "counterparty": counterparty,
                })

            dlg = TransactionReadOnlyDialog(self, account_name, rows)
            dlg.exec()
        finally:
            session.close()

# 向后兼容别名（accounts_page.py 使用此名称）
TransactionDialog = TransactionReadOnlyDialog
