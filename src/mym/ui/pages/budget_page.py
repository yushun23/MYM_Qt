"""BudgetPage – monthly budget tree with planned vs actual comparison."""

import logging
from decimal import Decimal

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.budget_service import (
    BudgetActuals,
    BudgetLineSummary,
    BudgetService,
)
from mym.domain.enums import BudgetStatus
from mym.ui.navigation import AppEventBus

logger = logging.getLogger(__name__)


class BudgetPage(QWidget):
    """Monthly budget management with planned vs actual tracking."""

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._current_period_id: int | None = None
        self._periods_data: list[dict] = []
        self._setup_ui()

        AppEventBus.instance().ledger_changed.connect(self.refresh)
        AppEventBus.instance().budget_changed.connect(self.refresh)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Top toolbar
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("预算月份:"))

        self._period_combo = QComboBox()
        self._period_combo.setMinimumWidth(200)
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        toolbar.addWidget(self._period_combo)

        toolbar.addSpacing(16)

        self._create_btn = QPushButton("新建月份")
        self._create_btn.clicked.connect(self._on_create_period)
        toolbar.addWidget(self._create_btn)

        self._copy_btn = QPushButton("从月份复制...")
        self._copy_btn.clicked.connect(self._on_copy_period)
        toolbar.addWidget(self._copy_btn)

        self._close_btn = QPushButton("关闭预算")
        self._close_btn.clicked.connect(self._on_toggle_close)
        toolbar.addWidget(self._close_btn)

        toolbar.addStretch()

        layout.addLayout(toolbar)

        # Summary bar
        summary_frame = QFrame()
        summary_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        summary_layout = QHBoxLayout(summary_frame)

        self._income_planned_lbl = QLabel("收入预算: —")
        self._income_actual_lbl = QLabel("收入实际: —")
        self._expense_planned_lbl = QLabel("支出预算: —")
        self._expense_actual_lbl = QLabel("支出实际: —")
        self._status_lbl = QLabel("")

        for lbl in [self._income_planned_lbl, self._income_actual_lbl,
                     self._expense_planned_lbl, self._expense_actual_lbl, self._status_lbl]:
            lbl.setStyleSheet("font-size: 13px; padding: 4px 12px;")
            summary_layout.addWidget(lbl)

        summary_layout.addStretch()
        layout.addWidget(summary_frame)

        # Budget tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([
            "名称", "预算金额", "实际金额", "执行率", "剩余", "状态"
        ])
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(True)
        self._tree.header().setStretchLastSection(True)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 6):
            self._tree.header().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree)

        # Bottom toolbar
        bottom_bar = QHBoxLayout()

        self._add_line_btn = QPushButton("添加预算项")
        self._add_line_btn.clicked.connect(self._on_add_line)
        bottom_bar.addWidget(self._add_line_btn)

        self._delete_line_btn = QPushButton("删除选中项")
        self._delete_line_btn.clicked.connect(self._on_delete_line)
        bottom_bar.addWidget(self._delete_line_btn)

        bottom_bar.addStretch()
        layout.addLayout(bottom_bar)

    def on_enter(self) -> None:
        self.refresh()

    def on_leave(self) -> None:
        pass

    def refresh(self) -> None:
        self._load_periods()

    def _session(self):
        if self._session_factory:
            return self._session_factory()
        return None

    def _load_periods(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            self._periods_data = svc.get_all_periods()
        finally:
            session.close()

        self._period_combo.blockSignals(True)
        self._period_combo.clear()
        for p in self._periods_data:
            status_mark = "🔒" if p["status"] == BudgetStatus.CLOSED else ""
            self._period_combo.addItem(f"{p['label']} {status_mark}", p["id"])
        self._period_combo.blockSignals(False)

        if self._periods_data:
            self._current_period_id = self._periods_data[0]["id"]
            self._period_combo.setCurrentIndex(0)
            self._load_tree()
        else:
            self._tree.clear()

    def _on_period_changed(self, idx: int) -> None:
        if idx >= 0 and self._periods_data:
            self._current_period_id = self._periods_data[idx]["id"]
            self._load_tree()

    def _load_tree(self) -> None:
        if self._current_period_id is None:
            return
        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            # Get actuals from transactions
            actuals = self._compute_actuals(session, svc)
            summaries = svc.get_period_summary(self._current_period_id, actuals)

            period = None
            for p in self._periods_data:
                if p["id"] == self._current_period_id:
                    period = p
                    break

            if period:
                self._income_planned_lbl.setText(
                    f"收入预算: ¥{period['planned_income']}"
                )
                self._income_actual_lbl.setText(
                    f"收入实际: ¥{actuals.total_income:,.2f}"
                )
                self._expense_planned_lbl.setText(
                    f"支出预算: ¥{period['planned_expense']}"
                )
                self._expense_actual_lbl.setText(
                    f"支出实际: ¥{actuals.total_expense:,.2f}"
                )
                if period["status"] == BudgetStatus.CLOSED:
                    self._status_lbl.setText("🔒 已关闭")
                    self._status_lbl.setStyleSheet(
                        "font-size: 13px; padding: 4px 12px; color: #D32F2F; font-weight: bold;"
                    )
                    self._close_btn.setText("重新打开")
                else:
                    self._status_lbl.setText("✅ 开启中")
                    self._status_lbl.setStyleSheet(
                        "font-size: 13px; padding: 4px 12px; color: #2E7D32; font-weight: bold;"
                    )
                    self._close_btn.setText("关闭预算")

                closed = period["status"] == BudgetStatus.CLOSED
                self._add_line_btn.setEnabled(not closed)
                self._delete_line_btn.setEnabled(not closed)

            self._tree.clear()
            income_root = QTreeWidgetItem(self._tree, ["📈 收入预算", "", "", "", "", ""])
            income_root.setExpanded(True)
            income_root.setFlags(income_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            income_root.setData(0, Qt.ItemDataRole.UserRole, "income_header")

            expense_root = QTreeWidgetItem(self._tree, ["📉 支出预算", "", "", "", "", ""])
            expense_root.setExpanded(True)
            expense_root.setFlags(expense_root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            expense_root.setData(0, Qt.ItemDataRole.UserRole, "expense_header")

            for s in summaries:
                parent = income_root if s.budget_type == "income" else expense_root
                self._add_summary_to_tree(parent, s)
        finally:
            session.close()

    def _add_summary_to_tree(
        self, parent: QTreeWidgetItem, summary: BudgetLineSummary
    ) -> None:
        """Recursively add budget line summary to tree."""
        pct_str = f"{summary.execution_pct}%"
        ram_str = f"¥{summary.remaining:,.2f}"

        if summary.is_over_budget:
            status = "⚠️ 超预算"
        elif summary.is_group and summary.children:
            status = ""
        else:
            status = "正常"

        item = QTreeWidgetItem(parent, [
            summary.name,
            f"¥{summary.planned_amount:,.2f}",
            f"¥{summary.actual_amount:,.2f}",
            pct_str,
            ram_str,
            status,
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, summary.id)

        # Color coding
        if summary.is_over_budget:
            for col in range(6):
                item.setForeground(col, QBrush(QColor("#D32F2F")))
        elif summary.planned_amount > 0 and summary.execution_pct >= 80:
            for col in range(6):
                item.setForeground(col, QBrush(QColor("#ED6C02")))

        for child in summary.children:
            self._add_summary_to_tree(item, child)

    def _compute_actuals(
        self, session, svc: BudgetService
    ) -> BudgetActuals:
        """Compute actual income/expense from transactions for the current period."""
        from sqlalchemy import select, func

        from mym.domain.entities.transaction import Transaction, TransactionLine
        from mym.domain.enums import TransactionStatus

        actuals = BudgetActuals()

        if self._current_period_id is None:
            return actuals

        # Find the period's year/month
        period = None
        for p in self._periods_data:
            if p["id"] == self._current_period_id:
                period = p
                break
        if not period:
            return actuals

        year, month = period["year"], period["month"]

        # Query posted transactions for that month
        stmt = (
            select(
                TransactionLine.category_id,
                func.sum(TransactionLine.signed_amount),
            )
            .join(Transaction, TransactionLine.transaction_id == Transaction.id)
            .where(
                Transaction.status == TransactionStatus.POSTED,
                func.strftime("%Y", Transaction.transaction_date) == str(year),
                func.strftime("%m", Transaction.transaction_date) == f"{month:02d}",
                TransactionLine.category_id.isnot(None),
            )
            .group_by(TransactionLine.category_id)
        )
        rows = session.execute(stmt).all()

        from mym.domain.entities.category import Category
        from mym.domain.enums import CategoryType

        for cat_id, total in rows:
            cat = session.get(Category, cat_id)
            if cat:
                if cat.category_type == CategoryType.INCOME:
                    actuals.total_income += total
                    actuals.by_category[cat_id] = total
                elif cat.category_type == CategoryType.EXPENSE:
                    actuals.total_expense += total
                    actuals.by_category[cat_id] = total

        return actuals

    # --- Actions ---

    def _on_create_period(self) -> None:
        from PySide6.QtWidgets import QDialog, QFormLayout, QSpinBox, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("新建预算月份")
        fl = QFormLayout(dlg)

        today = __import__("datetime").date.today()
        year_spin = QSpinBox()
        year_spin.setRange(2000, 2100)
        year_spin.setValue(today.year)
        month_spin = QSpinBox()
        month_spin.setRange(1, 12)
        month_spin.setValue(today.month)

        fl.addRow("年份:", year_spin)
        fl.addRow("月份:", month_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            result = svc.create_period(year_spin.value(), month_spin.value())
            if result.success:
                session.commit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_copy_period(self) -> None:
        if not self._periods_data:
            QMessageBox.information(self, "提示", "请先创建预算月份")
            return

        from PySide6.QtWidgets import QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("从月份复制预算")
        fl = QFormLayout(dlg)

        src_combo = QComboBox()
        for p in self._periods_data:
            src_combo.addItem(p["label"], (p["year"], p["month"]))
        fl.addRow("源月份:", src_combo)

        today = __import__("datetime").date.today()
        year_spin = QSpinBox()
        year_spin.setRange(2000, 2100)
        year_spin.setValue(today.year)
        month_spin = QSpinBox()
        month_spin.setRange(1, 12)
        month_spin.setValue(today.month)
        fl.addRow("目标年份:", year_spin)
        fl.addRow("目标月份:", month_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        src_year, src_month = src_combo.currentData()
        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            result = svc.copy_from_month(
                src_year, src_month, year_spin.value(), month_spin.value()
            )
            if result.success:
                session.commit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_toggle_close(self) -> None:
        if self._current_period_id is None:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            period = svc._repo.get_period(self._current_period_id)
            if not period:
                return

            if period.status == BudgetStatus.CLOSED:
                result = svc.reopen_period(self._current_period_id)
            else:
                reply = QMessageBox.question(
                    self, "确认关闭",
                    f"确定要关闭 {period.period_label} 的预算吗？\n关闭后预算数据将被保存为快照。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                result = svc.close_period(self._current_period_id)

            if result.success:
                session.commit()
                AppEventBus.instance().budget_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_add_line(self) -> None:
        if self._current_period_id is None:
            QMessageBox.information(self, "提示", "请先选择预算月份")
            return

        from PySide6.QtWidgets import (
            QDialog, QFormLayout, QLineEdit, QComboBox,
            QDoubleSpinBox, QCheckBox, QDialogButtonBox,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("添加预算项")
        fl = QFormLayout(dlg)

        name_edit = QLineEdit()
        fl.addRow("名称:", name_edit)

        type_combo = QComboBox()
        type_combo.addItems(["income", "expense"])
        fl.addRow("类型:", type_combo)

        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0, 999999999.99)
        amount_spin.setDecimals(2)
        amount_spin.setValue(0)
        fl.addRow("预算金额:", amount_spin)

        group_check = QCheckBox("分组项（非叶子节点）")
        fl.addRow("", group_check)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "错误", "名称不能为空")
            return

        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            result = svc.add_line(
                period_id=self._current_period_id,
                name=name,
                budget_type=type_combo.currentText(),
                planned_amount=Decimal(str(amount_spin.value())),
                is_group=group_check.isChecked(),
            )
            if result.success:
                session.commit()
                AppEventBus.instance().budget_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_delete_line(self) -> None:
        item = self._tree.currentItem()
        if not item:
            return

        line_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(line_id, int):
            return

        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除预算项「{item.text(0)}」吗？\n子项也会一并删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            result = svc.delete_line(line_id)
            if result.success:
                session.commit()
                AppEventBus.instance().budget_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Edit planned amount on double-click."""
        line_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(line_id, int):
            return

        from PySide6.QtWidgets import QDialog, QFormLayout, QDoubleSpinBox, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑预算: {item.text(0)}")
        fl = QFormLayout(dlg)

        current = item.text(1).replace("¥", "").replace(",", "")
        amount_spin = QDoubleSpinBox()
        amount_spin.setRange(0, 999999999.99)
        amount_spin.setDecimals(2)
        try:
            amount_spin.setValue(float(current))
        except ValueError:
            amount_spin.setValue(0)
        fl.addRow("预算金额:", amount_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = BudgetService(session)
            result = svc.update_line_planned(
                line_id, Decimal(str(amount_spin.value()))
            )
            if result.success:
                session.commit()
                AppEventBus.instance().budget_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()
