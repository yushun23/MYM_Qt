"""Record page – income, expense, and transfer entry."""

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.application.use_cases.create_transaction import CreateTransactionUseCase
from mym.ui.widgets.date_edit import SafeDateEdit
from mym.ui.widgets.dialogs import show_error, show_info


class RecordPage(QWidget):
    """Record income, expense, or transfer."""

    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        self._income_widget = self._build_income_form()
        self._expense_widget = self._build_expense_form()
        self._transfer_widget = self._build_transfer_form()

        tabs.addTab(self._income_widget, "收入")
        tabs.addTab(self._expense_widget, "支出")
        tabs.addTab(self._transfer_widget, "转账")
        layout.addWidget(tabs)

    def _build_income_form(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._income_date = SafeDateEdit()
        self._income_amount = QLineEdit()
        self._income_amount.setPlaceholderText("0.00")
        self._income_account = QComboBox()
        self._income_category = QComboBox()
        self._income_memo = QLineEdit()
        form.addRow("日期", self._income_date)
        form.addRow("金额", self._income_amount)
        form.addRow("账户", self._income_account)
        form.addRow("分类", self._income_category)
        form.addRow("备注", self._income_memo)

        btn = QPushButton("保存 (Ctrl+Enter)")
        btn.clicked.connect(self._save_income)
        form.addRow(btn)
        return w

    def _build_expense_form(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._expense_date = SafeDateEdit()
        self._expense_amount = QLineEdit()
        self._expense_amount.setPlaceholderText("0.00")
        self._expense_account = QComboBox()
        self._expense_category = QComboBox()
        self._expense_memo = QLineEdit()
        form.addRow("日期", self._expense_date)
        form.addRow("金额", self._expense_amount)
        form.addRow("账户", self._expense_account)
        form.addRow("分类", self._expense_category)
        form.addRow("备注", self._expense_memo)

        btn = QPushButton("保存 (Ctrl+Enter)")
        btn.clicked.connect(self._save_expense)
        form.addRow(btn)
        return w

    def _build_transfer_form(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self._transfer_date = SafeDateEdit()
        self._transfer_amount = QLineEdit()
        self._transfer_amount.setPlaceholderText("0.00")
        self._transfer_from = QComboBox()
        self._transfer_to = QComboBox()
        self._transfer_memo = QLineEdit()
        form.addRow("日期", self._transfer_date)
        form.addRow("金额", self._transfer_amount)
        form.addRow("转出账户", self._transfer_from)
        form.addRow("转入账户", self._transfer_to)
        form.addRow("备注", self._transfer_memo)

        btn = QPushButton("保存 (Ctrl+Enter)")
        btn.clicked.connect(self._save_transfer)
        form.addRow(btn)
        return w

    def on_enter(self):
        """Refresh account/category lists when page is shown."""
        self._refresh_combos()

    def on_leave(self):
        pass

    def _refresh_combos(self):
        session = self._session_factory()
        try:
            from mym.infrastructure.repositories.account_repo import AccountRepository
            from mym.infrastructure.repositories.category_repo import CategoryRepository
            from mym.domain.enums import CategoryType

            account_repo = AccountRepository(session)
            accounts = account_repo.get_enabled_normal()

            for cb in [self._income_account, self._expense_account,
                        self._transfer_from, self._transfer_to]:
                cb.clear()
                for a in accounts:
                    cb.addItem(a.name, a.id)

            cat_repo = CategoryRepository(session)
            income_cats = [c for c in cat_repo.get_all() if c.is_enabled and c.category_type == CategoryType.INCOME]
            expense_cats = [c for c in cat_repo.get_all() if c.is_enabled and c.category_type == CategoryType.EXPENSE]

            for cb, cats in [(self._income_category, income_cats), (self._expense_category, expense_cats)]:
                cb.clear()
                for c in cats:
                    cb.addItem(c.name, c.id)
        finally:
            session.close()

    def _save_income(self):
        self._save_transaction("income",
                               self._income_date, self._income_amount,
                               self._income_account, self._income_category,
                               self._income_memo)

    def _save_expense(self):
        self._save_transaction("expense",
                               self._expense_date, self._expense_amount,
                               self._expense_account, self._expense_category,
                               self._expense_memo)

    def _save_transfer(self):
        try:
            amount = Decimal(self._transfer_amount.text())
            from_id = self._transfer_from.currentData()
            to_id = self._transfer_to.currentData()
            if from_id == to_id:
                show_error(self, "错误", "转出和转入账户不能相同")
                return
        except Exception:
            show_error(self, "错误", "请输入有效金额")
            return

        dto = CreateTransactionDTO(
            business_type="transfer",
            transaction_date=self._transfer_date.get_date(),
            description=self._transfer_memo.text() or None,
            lines=[
                TransactionLineDTO(account_id=to_id, role="debit", signed_amount=amount),
                TransactionLineDTO(account_id=from_id, role="credit", signed_amount=amount),
            ],
        )
        self._execute(dto)

    def _save_transaction(self, biz_type, date_widget, amount_widget, account_cb, category_cb, memo_widget):
        try:
            amount = Decimal(amount_widget.text())
            account_id = account_cb.currentData()
            category_id = category_cb.currentData()
            if account_id is None or category_id is None:
                show_error(self, "错误", "请选择账户和分类")
                return
        except Exception:
            show_error(self, "错误", "请输入有效金额")
            return

        dto = CreateTransactionDTO(
            business_type=biz_type,
            transaction_date=date_widget.get_date(),
            description=memo_widget.text() or None,
            lines=[
                TransactionLineDTO(account_id=account_id, role="debit",
                                   signed_amount=amount, category_id=category_id),
                TransactionLineDTO(account_id=account_id, role="credit",
                                   signed_amount=amount, category_id=category_id),
            ],
        )
        self._execute(dto)

    def _execute(self, dto):
        session = self._session_factory()
        try:
            uc = CreateTransactionUseCase(session)
            result = uc.execute(dto)
            if result.success:
                session.commit()
                show_info(self, "成功", "记账成功")
                from mym.ui.navigation import AppEventBus
                AppEventBus.instance().ledger_changed.emit()
            else:
                session.rollback()
                show_error(self, "错误", "\n".join(result.errors))
        except Exception as e:
            session.rollback()
            show_error(self, "错误", str(e))
        finally:
            session.close()
