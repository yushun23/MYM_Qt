"""Transaction center – list, filter, edit, void transactions."""

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym.application.use_cases.void_transaction import VoidTransactionUseCase
from mym.ui.widgets.date_edit import SafeDateEdit
from mym.ui.widgets.dialogs import confirm_action, show_error, show_info
from mym.ui.widgets.table_model import BaseTableModel, ColumnDef


class TransactionPage(QWidget):
    """List, filter, and manage transactions."""

    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Filters
        filter_row = QHBoxLayout()
        self._date_from = SafeDateEdit()
        self._date_from.setDate(self._date_from.date().addMonths(-1))
        self._date_to = SafeDateEdit()
        self._filter_type = QComboBox()
        self._filter_type.addItem("全部", "")
        self._filter_type.addItem("收入", "income")
        self._filter_type.addItem("支出", "expense")
        self._filter_type.addItem("转账", "transfer")
        self._filter_search = QLineEdit()
        self._filter_search.setPlaceholderText("搜索备注...")

        filter_row.addWidget(QLabel("从"))
        filter_row.addWidget(self._date_from)
        filter_row.addWidget(QLabel("到"))
        filter_row.addWidget(self._date_to)
        filter_row.addWidget(self._filter_type)
        filter_row.addWidget(self._filter_search)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.on_enter)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        # Table
        columns = [
            ColumnDef("id", "ID", 50),
            ColumnDef("date", "日期", 100),
            ColumnDef("type", "类型", 60),
            ColumnDef("amount", "金额", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("description", "备注", 250),
            ColumnDef("source", "来源", 80),
            ColumnDef("status", "状态", 60),
        ]
        self._model = BaseTableModel(columns)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

        # Actions
        action_row = QHBoxLayout()
        void_btn = QPushButton("作废")
        void_btn.clicked.connect(self._void_selected)
        action_row.addWidget(void_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

    def on_enter(self):
        self._refresh()

    def on_leave(self):
        pass

    def _refresh(self):
        session = self._session_factory()
        try:
            from sqlalchemy import select
            from mym.domain.entities.transaction import Transaction

            stmt = select(Transaction).order_by(Transaction.transaction_date.desc()).limit(100)
            txs = session.execute(stmt).scalars().all()

            data = []
            for tx in txs:
                total = Decimal("0")
                for line in tx.lines:
                    if line.role.value == "debit":
                        total += line.signed_amount
                data.append({
                    "id": tx.id,
                    "date": str(tx.transaction_date),
                    "type": tx.business_type,
                    "amount": total,
                    "description": tx.description or "",
                    "source": tx.source.value,
                    "status": tx.status.value,
                })
            self._model.set_data(data)
        finally:
            session.close()

    def _void_selected(self):
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            show_error(self, "错误", "请先选择一条交易")
            return
        row = indexes[0].row()
        tx_data = self._model.get_row(row)
        if not tx_data:
            return
        tx_id = tx_data["id"]

        if not confirm_action(self, "确认作废", f"确定要作废交易 #{tx_id} 吗？"):
            return

        session = self._session_factory()
        try:
            uc = VoidTransactionUseCase(session)
            result = uc.execute(tx_id)
            if result.success:
                session.commit()
                show_info(self, "成功", "交易已作废")
                from mym.ui.navigation import AppEventBus
                AppEventBus.instance().ledger_changed.emit()
                self._refresh()
            else:
                session.rollback()
                show_error(self, "错误", "\n".join(result.errors))
        except Exception as e:
            session.rollback()
            show_error(self, "错误", str(e))
        finally:
            session.close()
