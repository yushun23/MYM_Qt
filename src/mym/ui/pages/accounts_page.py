"""Account and category management page."""

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
)

from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.enums import AccountType, CategoryType
from mym.ui.widgets.dialogs import confirm_action, show_error, show_info
from mym.ui.widgets.table_model import BaseTableModel, ColumnDef


class AccountCategoryPage(QWidget):
    """Manage accounts and categories."""

    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # Accounts tab
        acc_widget = QWidget()
        acc_layout = QVBoxLayout(acc_widget)
        acc_columns = [
            ColumnDef("id", "ID", 40),
            ColumnDef("name", "名称", 150),
            ColumnDef("type", "类型", 80),
            ColumnDef("balance", "当前余额", 120, Qt.AlignmentFlag.AlignRight),
            ColumnDef("status", "状态", 60),
        ]
        self._acc_model = BaseTableModel(acc_columns)
        self._acc_table = QTableView()
        self._acc_table.setModel(self._acc_model)
        self._acc_table.horizontalHeader().setStretchLastSection(True)
        acc_layout.addWidget(self._acc_table)

        acc_btn_row = QHBoxLayout()
        add_acc_btn = QPushButton("新增账户")
        add_acc_btn.clicked.connect(self._add_account)
        archive_acc_btn = QPushButton("归档选中")
        archive_acc_btn.clicked.connect(self._archive_account)
        acc_btn_row.addWidget(add_acc_btn)
        acc_btn_row.addWidget(archive_acc_btn)
        acc_btn_row.addStretch()
        acc_layout.addLayout(acc_btn_row)
        tabs.addTab(acc_widget, "账户")

        # Categories tab
        cat_widget = QWidget()
        cat_layout = QVBoxLayout(cat_widget)
        cat_columns = [
            ColumnDef("id", "ID", 40),
            ColumnDef("name", "名称", 150),
            ColumnDef("type", "类型", 80),
            ColumnDef("status", "状态", 60),
        ]
        self._cat_model = BaseTableModel(cat_columns)
        self._cat_table = QTableView()
        self._cat_table.setModel(self._cat_model)
        self._cat_table.horizontalHeader().setStretchLastSection(True)
        cat_layout.addWidget(self._cat_table)

        cat_btn_row = QHBoxLayout()
        add_cat_btn = QPushButton("新增分类")
        add_cat_btn.clicked.connect(self._add_category)
        cat_btn_row.addWidget(add_cat_btn)
        cat_btn_row.addStretch()
        cat_layout.addLayout(cat_btn_row)
        tabs.addTab(cat_widget, "分类")

        layout.addWidget(tabs)

    def on_enter(self):
        self._refresh()

    def on_leave(self):
        pass

    def _refresh(self):
        session = self._session_factory()
        try:
            from mym.infrastructure.repositories.account_repo import AccountRepository
            from mym.infrastructure.repositories.category_repo import CategoryRepository

            acc_repo = AccountRepository(session)
            accounts = acc_repo.get_all()
            acc_data = []
            for a in accounts:
                acc_data.append({
                    "id": a.id,
                    "name": a.name,
                    "type": a.account_type.value,
                    "balance": str(a.current_balance),
                    "status": "启用" if a.is_enabled else "禁用",
                })
            self._acc_model.set_data(acc_data)

            cat_repo = CategoryRepository(session)
            cats = cat_repo.get_all()
            cat_data = []
            for c in cats:
                cat_data.append({
                    "id": c.id,
                    "name": c.name,
                    "type": c.category_type.value,
                    "status": "启用" if c.is_enabled else "禁用",
                })
            self._cat_model.set_data(cat_data)
        finally:
            session.close()

    def _add_account(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("新增账户")
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        type_cb = QComboBox()
        type_cb.addItem("资产", AccountType.ASSET.value)
        type_cb.addItem("负债", AccountType.LIABILITY.value)
        balance_edit = QLineEdit("0.00")
        form.addRow("名称", name_edit)
        form.addRow("类型", type_cb)
        form.addRow("开户余额", balance_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            try:
                bal = Decimal(balance_edit.text())
            except Exception:
                show_error(self, "错误", "请输入有效金额")
                return

            session = self._session_factory()
            try:
                acc = Account(
                    name=name_edit.text(),
                    account_type=AccountType(type_cb.currentData()),
                    opening_balance=bal,
                    current_balance=bal,
                )
                session.add(acc)
                session.commit()
                show_info(self, "成功", "账户已创建")
                self._refresh()
            except Exception as e:
                session.rollback()
                show_error(self, "错误", str(e))
            finally:
                session.close()

    def _archive_account(self):
        indexes = self._acc_table.selectionModel().selectedRows()
        if not indexes:
            show_error(self, "错误", "请先选择一个账户")
            return
        row = indexes[0].row()
        acc_data = self._acc_model.get_row(row)
        if not acc_data:
            return

        if not confirm_action(self, "确认归档", f"确定归档账户 {acc_data['name']} 吗？"):
            return

        session = self._session_factory()
        try:
            from mym.infrastructure.repositories.account_repo import AccountRepository
            repo = AccountRepository(session)
            acc = repo.get_by_id(acc_data["id"])
            if acc:
                acc.is_archived = True
                session.commit()
                show_info(self, "成功", "账户已归档")
                self._refresh()
        except Exception as e:
            session.rollback()
            show_error(self, "错误", str(e))
        finally:
            session.close()

    def _add_category(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("新增分类")
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        type_cb = QComboBox()
        type_cb.addItem("收入", CategoryType.INCOME.value)
        type_cb.addItem("支出", CategoryType.EXPENSE.value)
        form.addRow("名称", name_edit)
        form.addRow("类型", type_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            session = self._session_factory()
            try:
                cat = Category(
                    name=name_edit.text(),
                    category_type=CategoryType(type_cb.currentData()),
                )
                session.add(cat)
                session.commit()
                show_info(self, "成功", "分类已创建")
                self._refresh()
            except Exception as e:
                session.rollback()
                show_error(self, "错误", str(e))
            finally:
                session.close()
