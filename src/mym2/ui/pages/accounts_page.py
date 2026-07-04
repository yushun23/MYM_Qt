"""账户管理页面 — QTableView + QAbstractTableModel。

支持资产、负债、应收账户的新建、编辑、启停、分组、期初余额。
已有流水的账户禁止物理删除，改为停用；锁定历史投资快照账户不可编辑/删除。
所有写操作通过 AccountService。
"""

from __future__ import annotations

import csv
import logging
from contextlib import suppress
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from mym2.db.models.account import Account
from mym2.db.models.transaction import Transaction
from mym2.db.session import get_session
from mym2.domain.enums import AccountType
from mym2.repositories.account_repo import AccountRepository
from mym2.services.account_service import AccountService
from mym2.services.dto import CreateAccountDTO, UpdateAccountDTO

logger = logging.getLogger("mym2.ui.accounts_page")

ACCOUNT_TYPE_LABELS: dict[str, str] = {
    "cash": "现金",
    "bank": "银行卡",
    "credit_card": "信用卡",
    "investment_snapshot": "投资快照",
    "receivable": "应收",
}

GROUP_OPTIONS = ["", "现金", "银行", "信用", "投资", "应收", "其他"]


def _minor_to_yuan(minor: int) -> str:
    """将整数分格式化为元显示。"""
    sign = "-" if minor < 0 else ""
    val = abs(minor)
    yuan = val // 100
    fen = val % 100
    return f"{sign}{yuan}.{fen:02d}"


class AccountTableModel(QAbstractTableModel):
    """账户表格数据模型。

    Columns: name, type, group, opening_balance, current_balance, status, currency.
    """

    COLUMNS = ["名称", "类型", "分组", "期初余额", "当前余额", "状态", "币种"]
    _data: list[dict[str, Any]]
    _raw_accounts: list[Account]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = []
        self._raw_accounts = []

    def load_data(self, accounts: list[Account]) -> None:
        """从 Account 列表加载数据。"""
        self.beginResetModel()
        self._raw_accounts = accounts
        self._data = [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type,
                "type_label": ACCOUNT_TYPE_LABELS.get(a.type, a.type),
                "group": a.group or "",
                "opening_balance_minor": a.opening_balance_minor,
                "current_balance_minor": a.current_balance_minor,
                "is_enabled": a.is_enabled,
                "is_locked": a.is_locked,
                "is_editable": a.is_editable,
                "currency": a.currency,
            }
            for a in accounts
        ]
        self.endResetModel()

    def get_account_id(self, row: int) -> str | None:
        """获取指定行的账户 ID。"""
        if 0 <= row < len(self._data):
            return self._data[row]["id"]
        return None

    def get_account(self, row: int) -> dict[str, Any] | None:
        """获取指定行的账户数据字典。"""
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        item = self._data[row]

        if role == Qt.DisplayRole:
            if col == 0:
                return item["name"]
            elif col == 1:
                return item["type_label"]
            elif col == 2:
                return item["group"]
            elif col == 3:
                return _minor_to_yuan(item["opening_balance_minor"])
            elif col == 4:
                return _minor_to_yuan(item["current_balance_minor"])
            elif col == 5:
                if item["is_locked"]:
                    return "已锁定"
                return "启用" if item["is_enabled"] else "已停用"
            elif col == 6:
                return item["currency"]

        elif role == Qt.ForegroundRole:
            if not item["is_enabled"]:
                return QColor("#888888")
            if item["is_locked"]:
                return QColor("#ff9900")

        elif role == Qt.UserRole:
            return item

        return None


class AccountDialog(QDialog):
    """新建/编辑账户对话框。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        account_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_edit = account_data is not None
        self.setWindowTitle("编辑账户" if self._is_edit else "新建账户")
        self.setMinimumWidth(400)
        self._setup_ui(account_data)

    def _setup_ui(self, account_data: dict[str, Any] | None) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("账户名称")
        form.addRow("名称:", self._name_edit)

        self._type_combo = QComboBox()
        for t in AccountType:
            self._type_combo.addItem(ACCOUNT_TYPE_LABELS.get(t.value, t.value), t.value)
        form.addRow("类型:", self._type_combo)

        self._group_combo = QComboBox()
        self._group_combo.setEditable(True)
        for g in GROUP_OPTIONS:
            self._group_combo.addItem(g if g else "(无)", g)
        form.addRow("分组:", self._group_combo)

        self._opening_edit = QLineEdit()
        self._opening_edit.setPlaceholderText("0.00")
        form.addRow("期初余额:", self._opening_edit)

        self._currency_edit = QLineEdit("CNY")
        self._currency_edit.setMaxLength(10)
        form.addRow("币种:", self._currency_edit)

        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("备注（可选）")
        form.addRow("备注:", self._notes_edit)

        layout.addLayout(form)

        if self._is_edit and account_data:
            self._name_edit.setText(account_data["name"])
            idx = self._type_combo.findData(account_data["type"])
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            gidx = self._group_combo.findData(account_data.get("group", ""))
            if gidx >= 0:
                self._group_combo.setCurrentIndex(gidx)
            self._opening_edit.setText(
                _minor_to_yuan(account_data.get("opening_balance_minor", 0))
            )
            self._currency_edit.setText(account_data.get("currency", "CNY"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        """验证输入后接受对话框。"""
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "验证失败", "账户名称不能为空")
            return

        yuan_text = self._opening_edit.text().strip()
        if not yuan_text:
            yuan_text = "0"
        try:
            from decimal import Decimal

            d = Decimal(yuan_text)
            opening_minor = int((d * 100).quantize(Decimal("1")))
        except Exception:
            QMessageBox.warning(self, "验证失败", f"期初余额格式无效: {yuan_text}")
            return

        self._result = {
            "name": name,
            "type": self._type_combo.currentData(),
            "group": self._group_combo.currentData() or None,
            "opening_balance_minor": opening_minor,
            "currency": self._currency_edit.text().strip() or "CNY",
            "notes": self._notes_edit.text().strip() or None,
        }
        self.accept()

    def get_data(self) -> dict[str, Any]:
        return getattr(self, "_result", {})


class TransactionDialog(QDialog):
    """账户流水钻取对话框（只读）。"""

    def __init__(
        self, parent: QWidget | None, account_name: str, transactions: list[dict]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{account_name} — 流水明细")
        self.resize(700, 400)
        layout = QVBoxLayout(self)

        table = QTableView()
        model = _TxTableModel(transactions)
        table.setModel(model)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class _TxTableModel(QAbstractTableModel):
    COLUMNS = ["日期", "类型", "金额", "分类", "备注", "对方账户"]

    def __init__(self, rows: list[dict], parent=None):
        super().__init__(parent)
        self._rows = rows

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == Qt.DisplayRole:
            cols = [
                row.get("date", ""),
                row.get("type", ""),
                row.get("amount", ""),
                row.get("category", ""),
                row.get("note", ""),
                row.get("counterparty", ""),
            ]
            return cols[index.column()]
        return None


TX_TYPE_LABELS = {
    "expense": "支出",
    "income": "收入",
    "transfer": "转账",
    "receivable_advance": "应收垫付",
    "receivable_repayment": "应收还款",
    "balance_adjustment": "余额调节",
    "historical_investment_settlement": "历史投资结算",
}


class AccountsPage(QWidget):
    """账户管理页面。

    使用 QTableView + QAbstractTableModel + AccountFilterProxy。
    """

    account_saved = Signal()
    navigate_to = Signal(str)
    """账户管理页面。

    使用 QTableView + QAbstractTableModel + QSortFilterProxyModel。
    """

    account_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._account_service = AccountService()
        self._setup_ui()
        # 数据延迟加载：首次 showEvent 时刷新

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # 标题行
        header_layout = QHBoxLayout()
        title = QLabel("账户管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._show_disabled_cb = QCheckBox("显示已停用")
        self._show_disabled_cb.toggled.connect(self._on_filter_changed)
        header_layout.addWidget(self._show_disabled_cb)

        btn_new = QPushButton("+ 新建账户")
        btn_new.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: #fff; padding: 6px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #3b5de7; }"
        )
        btn_new.clicked.connect(self._on_new_account)
        header_layout.addWidget(btn_new)
        layout.addLayout(header_layout)

        # 表格
        self._table = QTableView()
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            "QTableView { background: #252738; alternate-background-color: #2a2d40; "
            "gridline-color: #3a3d50; color: #ddd; }"
            "QTableView::item:selected { background: #4a6cf7; }"
            "QHeaderView::section { background: #2b2d3e; color: #aaa; "
            "padding: 4px; border: none; }"
        )

        self._source_model = AccountTableModel(self)
        self._proxy_model = AccountFilterProxy(self)
        self._proxy_model.setSourceModel(self._source_model)
        self._proxy_model.setFilterKeyColumn(-1)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._table.setModel(self._proxy_model)

        layout.addWidget(self._table)

        # 底部操作栏
        bottom_layout = QHBoxLayout()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索账户...")
        self._search_edit.textChanged.connect(self._on_filter_changed)
        bottom_layout.addWidget(self._search_edit)

        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(self._on_edit_account)
        bottom_layout.addWidget(btn_edit)

        btn_toggle = QPushButton("启停")
        btn_toggle.clicked.connect(self._on_toggle_account)
        bottom_layout.addWidget(btn_toggle)

        btn_transactions = QPushButton("流水明细")
        btn_transactions.clicked.connect(self._on_view_transactions)
        bottom_layout.addWidget(btn_transactions)

        btn_export = QPushButton("导出 CSV")
        btn_export.clicked.connect(self._on_export_csv)
        bottom_layout.addWidget(btn_export)

        btn_archive = QPushButton("历史归档")
        btn_archive.clicked.connect(lambda: self.navigate_to.emit("history_archive"))
        bottom_layout.addWidget(btn_archive)

        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

        # 右键菜单
        self._table.setContextMenuPolicy(Qt.ActionsContextMenu)
        act_view = QAction("查看流水明细", self)
        act_view.triggered.connect(self._on_view_transactions)
        self._table.addAction(act_view)

        act_export = QAction("导出当前筛选为 CSV", self)
        act_export.triggered.connect(self._on_export_csv)
        self._table.addAction(act_export)

    # ── 数据加载 ──────────────────────────────────────

    _first_show: bool = True

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            with suppress(RuntimeError):
                self.refresh()  # Session factory 未初始化（测试模式）

    def refresh(self) -> None:
        """刷新账户列表。"""
        session = get_session()
        try:
            repo = AccountRepository(session)
            accounts = repo.get_all()
            self._source_model.load_data(accounts)
            self._on_filter_changed()
        finally:
            session.close()

    # ── 筛选 ──────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        """应用筛选。"""
        show_disabled = self._show_disabled_cb.isChecked()
        search_text = self._search_edit.text().strip()
        self._proxy_model.set_show_disabled(show_disabled)
        self._proxy_model.setFilterFixedString(search_text)
        self._proxy_model.invalidateFilter()

    # ── 操作 ──────────────────────────────────────────

    def _get_selected_account(self) -> dict[str, Any] | None:
        """获取当前选中行的账户数据。"""
        proxy_indexes = self._table.selectionModel().selectedRows()
        if not proxy_indexes:
            return None
        source_index = self._proxy_model.mapToSource(proxy_indexes[0])
        return self._source_model.get_account(source_index.row())

    def _on_new_account(self) -> None:
        """打开新建账户对话框。"""
        dlg = AccountDialog(self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            try:
                session = get_session()
                try:
                    dto = CreateAccountDTO(
                        name=data["name"],
                        type=data["type"],
                        group=data.get("group"),
                        opening_balance_minor=data.get("opening_balance_minor", 0),
                        currency=data.get("currency", "CNY"),
                        notes=data.get("notes"),
                    )
                    with session.begin():
                        self._account_service.create_account(session, dto)
                finally:
                    session.close()
                self.refresh()
                self.account_saved.emit()
            except ValueError as e:
                QMessageBox.warning(self, "创建失败", str(e))

    def _on_edit_account(self) -> None:
        """打开编辑账户对话框。"""
        item = self._get_selected_account()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择要编辑的账户")
            return

        if item.get("is_locked"):
            QMessageBox.warning(
                self,
                "无法编辑",
                f'"{item["name"]}" 为历史投资快照账户，不可编辑。',
            )
            return

        if not item.get("is_editable", True):
            QMessageBox.warning(
                self,
                "无法编辑",
                f'"{item["name"]}" 不可编辑。',
            )
            return

        dlg = AccountDialog(self, account_data=item)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            try:
                session = get_session()
                try:
                    # 检测变化
                    dto = UpdateAccountDTO()
                    if data["name"] != item["name"]:
                        dto.name = data["name"]
                    if data["type"] != item["type"]:
                        dto.type = data["type"]
                    if data.get("group") != item.get("group"):
                        dto.group = data.get("group")
                    if data.get("opening_balance_minor") != item.get("opening_balance_minor"):
                        dto.opening_balance_minor = data.get("opening_balance_minor")
                    if data.get("currency") != item.get("currency"):
                        dto.currency = data.get("currency")
                    if data.get("notes") != item.get("notes", None):
                        dto.notes = data.get("notes")

                    with session.begin():
                        self._account_service.update_account(
                            session, item["id"], dto
                        )
                finally:
                    session.close()
                self.refresh()
                self.account_saved.emit()
            except ValueError as e:
                QMessageBox.warning(self, "编辑失败", str(e))

    def _on_toggle_account(self) -> None:
        """启停账户。"""
        item = self._get_selected_account()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择账户")
            return

        if item.get("is_locked"):
            QMessageBox.warning(
                self,
                "无法操作",
                f'"{item["name"]}" 已锁定，无法启停。',
            )
            return

        try:
            session = get_session()
            try:
                with session.begin():
                    if item["is_enabled"]:
                        self._account_service.disable_account(session, item["id"])
                    else:
                        self._account_service.enable_account(session, item["id"])
            finally:
                session.close()
            self.refresh()
            self.account_saved.emit()
        except ValueError as e:
            QMessageBox.warning(self, "操作失败", str(e))

    def _on_view_transactions(self) -> None:
        """查看选中账户的流水明细（只读）。"""
        item = self._get_selected_account()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择账户")
            return

        session = get_session()
        try:
            txs = session.scalars(
                select(Transaction).where(
                    (Transaction.account_out_id == item["id"])
                    | (Transaction.account_in_id == item["id"])
                ).order_by(Transaction.transaction_date.desc())
            ).all()

            rows = []
            for tx in txs:
                cat_name = tx.category.name if tx.category else ""
                counterparty = ""
                if tx.account_out_id != item["id"] and tx.account_out:
                    counterparty = tx.account_out.name
                elif tx.account_in_id != item["id"] and tx.account_in:
                    counterparty = tx.account_in.name

                rows.append({
                    "date": str(tx.transaction_date),
                    "type": TX_TYPE_LABELS.get(tx.type, tx.type),
                    "amount": _minor_to_yuan(tx.amount_minor),
                    "category": cat_name,
                    "note": tx.note or "",
                    "counterparty": counterparty,
                })

            dlg = TransactionDialog(self, item["name"], rows)
            dlg.exec()
        finally:
            session.close()

    def _on_export_csv(self) -> None:
        """按当前筛选导出 CSV。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", "accounts.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(AccountTableModel.COLUMNS)

                proxy = self._proxy_model
                for row in range(proxy.rowCount()):
                    row_data = []
                    for col in range(proxy.columnCount()):
                        idx = proxy.index(row, col)
                        row_data.append(proxy.data(idx, Qt.DisplayRole))
                    writer.writerow(row_data)

            QMessageBox.information(self, "导出完成", f"已导出到:\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))


# ── QSortFilterProxyModel 子类，支持 show_disabled 过滤 ──

class AccountFilterProxy(QSortFilterProxyModel):
    """支持显示/隐藏已停用账户的代理模型。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._show_disabled = False

    def set_show_disabled(self, show: bool) -> None:
        self._show_disabled = show
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._show_disabled:
            idx = self.sourceModel().index(source_row, 0, source_parent)
            item = self.sourceModel().data(idx, Qt.UserRole)
            if item and not item.get("is_enabled", True):
                return False
        return super().filterAcceptsRow(source_row, source_parent)
