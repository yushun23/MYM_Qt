"""预算管理页面 — 月度预算设定与实际对比。

功能：
- 月度切换（上/下月）
- 创建新预算、复制上月
- 预算明细表（分类、分组、计划金额、实际发生、剩余、进度、状态）
- 添加/编辑/删除明细行
- 关闭/重新打开月份
- 汇总统计
"""

from __future__ import annotations

import logging

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym2.db.session import get_session
from mym2.repositories.budget_repo import BudgetRepository
from mym2.services.budget_service import BudgetService
from mym2.services.dto import (
    BudgetLineDTO,
    CopyBudgetDTO,
    CreateBudgetPeriodDTO,
    UpdateBudgetLineDTO,
)

logger = logging.getLogger('mym2.ui.budget_page')


def _minor_to_yuan(minor: int) -> str:
    """将整数分格式化为元显示。"""
    sign = '-' if minor < 0 else ''
    val = abs(minor)
    return f'{sign}{val // 100}.{val % 100:02d}'


class BudgetTableModel(QAbstractTableModel):
    """预算明细表格模型。

    Columns: 分类, 类型, 分组, 计划金额, 实际金额, 剩余, 进度, 状态.
    """

    COLUMNS = ['分类', '类型', '分组', '计划金额', '实际金额', '剩余', '进度', '状态']

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._is_closed = False

    def load_data(
        self,
        lines: list,
        is_closed: bool = False,
    ) -> None:
        """加载预算明细数据。"""
        self.beginResetModel()
        self._is_closed = is_closed
        self._rows = []
        for lv in lines:
            status = '超支' if lv.is_over else ('正常' if lv.progress_pct < 100 else '已达')
            self._rows.append({
                'line_id': lv.line.id,
                'category_name': lv.category_name,
                'category_color': lv.category_color,
                'type': lv.line.type,
                'type_label': '支出' if lv.line.type == 'expense' else '收入',
                'group': lv.line.group or '',
                'planned_minor': lv.line.amount_minor,
                'actual_minor': lv.actual_minor,
                'remaining_minor': lv.remaining_minor,
                'progress_pct': lv.progress_pct,
                'is_over': lv.is_over,
                'status': status,
            })
        self.endResetModel()

    def get_line_id(self, row: int) -> str | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]['line_id']
        return None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> object:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        item = self._rows[row]

        if role == Qt.DisplayRole:
            if col == 0:
                return item['category_name']
            elif col == 1:
                return item['type_label']
            elif col == 2:
                return item['group']
            elif col == 3:
                return _minor_to_yuan(item['planned_minor'])
            elif col == 4:
                return _minor_to_yuan(item['actual_minor'])
            elif col == 5:
                return _minor_to_yuan(item['remaining_minor'])
            elif col == 6:
                return f'{item["progress_pct"]:.1f}%'
            elif col == 7:
                return item['status']

        elif role == Qt.ForegroundRole:
            if col == 5 and item['remaining_minor'] < 0:
                return QColor('#e74c3c')
            if col == 6 and item['is_over']:
                return QColor('#e74c3c')
            if col == 7 and item['is_over']:
                return QColor('#e74c3c')

        elif role == Qt.BackgroundRole:
            if item['is_over']:
                return QColor('#3d2020')
            if item['progress_pct'] >= 100:
                return QColor('#2d3d20')

        return None


class BudgetPage(QWidget):
    """预算管理页面。"""

    navigate_to = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = BudgetService()
        self._current_year: int = 0
        self._current_month: int = 0
        self._current_period_id: str | None = None
        self._is_closed = False

        self._setup_ui()
        self._init_current_month()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 顶部：月份切换 ──
        top_row = QHBoxLayout()

        self._prev_btn = QPushButton('◀ 上月')
        self._prev_btn.clicked.connect(self._go_prev_month)
        top_row.addWidget(self._prev_btn)

        self._month_label = QLabel()
        self._month_label.setStyleSheet('font-size: 20px; font-weight: bold; color: #fff;')
        self._month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self._month_label, 1)

        self._next_btn = QPushButton('下月 ▶')
        self._next_btn.clicked.connect(self._go_next_month)
        top_row.addWidget(self._next_btn)

        layout.addLayout(top_row)

        # ── 操作按钮行 ──
        action_row = QHBoxLayout()

        self._create_btn = QPushButton('新建预算')
        self._create_btn.clicked.connect(self._on_create)
        action_row.addWidget(self._create_btn)

        self._copy_btn = QPushButton('复制上月')
        self._copy_btn.clicked.connect(self._on_copy)
        action_row.addWidget(self._copy_btn)

        self._add_line_btn = QPushButton('+ 添加行')
        self._add_line_btn.clicked.connect(self._on_add_line)
        action_row.addWidget(self._add_line_btn)

        self._edit_btn = QPushButton('编辑选中行')
        self._edit_btn.clicked.connect(self._on_edit_line)
        action_row.addWidget(self._edit_btn)

        self._delete_btn = QPushButton('删除选中行')
        self._delete_btn.clicked.connect(self._on_delete_line)
        action_row.addWidget(self._delete_btn)

        action_row.addStretch()

        self._close_btn = QPushButton('关闭月份')
        self._close_btn.clicked.connect(self._on_close_period)
        action_row.addWidget(self._close_btn)

        self._reopen_btn = QPushButton('重新打开')
        self._reopen_btn.clicked.connect(self._on_reopen_period)
        self._reopen_btn.hide()
        action_row.addWidget(self._reopen_btn)

        layout.addLayout(action_row)

        # ── 汇总行 ──
        summary_row = QHBoxLayout()
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet(
            'font-size: 14px; color: #aaa; padding: 4px 0;'
        )
        summary_row.addWidget(self._summary_label)
        summary_row.addStretch()
        layout.addLayout(summary_row)

        # ── 表格 ──
        self._model = BudgetTableModel(self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(self._table_style())
        self._table.doubleClicked.connect(self._on_edit_line)
        layout.addWidget(self._table, 1)

    def _table_style(self) -> str:
        return """
            QTableView {
                background: #2b2d3e;
                border: 1px solid #444;
                border-radius: 4px;
                gridline-color: #3a3f4b;
                font-size: 13px;
            }
            QTableView::item {
                padding: 6px 8px;
            }
            QTableView::item:selected {
                background: #4a6cf7;
            }
            QHeaderView::section {
                background: #1e1f2b;
                color: #999;
                padding: 6px 8px;
                border: none;
                border-bottom: 2px solid #4a6cf7;
                font-size: 12px;
                font-weight: bold;
            }
        """

    # ── 月份导航 ──

    def _init_current_month(self) -> None:
        from datetime import date
        today = date.today()
        self._current_year = today.year
        self._current_month = today.month

    def _go_prev_month(self) -> None:
        if self._current_month == 1:
            self._current_month = 12
            self._current_year -= 1
        else:
            self._current_month -= 1
        self.refresh()

    def _go_next_month(self) -> None:
        if self._current_month == 12:
            self._current_month = 1
            self._current_year += 1
        else:
            self._current_month += 1
        self.refresh()

    # ── 刷新 ──

    def refresh(self) -> None:
        """刷新当前月份的预算视图。"""
        self._month_label.setText(
            f'{self._current_year}年 {self._current_month}月'
        )

        session = get_session()
        try:
            repo = BudgetRepository(session)
            view = repo.build_period_view(
                self._current_year, self._current_month
            )

            if view is None:
                self._model.load_data([], is_closed=False)
                self._current_period_id = None
                self._is_closed = False
                self._summary_label.setText('暂无预算数据')
                self._create_btn.setEnabled(True)
                self._copy_btn.setEnabled(True)
                self._add_line_btn.setEnabled(False)
                self._edit_btn.setEnabled(False)
                self._delete_btn.setEnabled(False)
                self._close_btn.hide()
                self._reopen_btn.hide()
                return

            self._current_period_id = view.period.id
            self._is_closed = view.period.is_closed
            self._model.load_data(view.lines, is_closed=self._is_closed)

            planned = view.planned_total
            actual = view.actual_total
            remaining = planned - actual

            self._summary_label.setText(
                f'计划 {_minor_to_yuan(planned)} | '
                f'实际 {_minor_to_yuan(actual)} | '
                f'剩余 {_minor_to_yuan(remaining)} | '
                f'{len(view.lines)} 项'
            )

            # 按钮状态
            if self._is_closed:
                self._create_btn.setEnabled(False)
                self._copy_btn.setEnabled(False)
                self._add_line_btn.setEnabled(False)
                self._edit_btn.setEnabled(False)
                self._delete_btn.setEnabled(False)
                self._close_btn.hide()
                self._reopen_btn.show()
            else:
                self._create_btn.setEnabled(False)
                self._copy_btn.setEnabled(False)
                self._add_line_btn.setEnabled(True)
                self._edit_btn.setEnabled(True)
                self._delete_btn.setEnabled(True)
                self._close_btn.show()
                self._reopen_btn.hide()

        finally:
            session.close()

    # ── 操作：创建 ──

    def _on_create(self) -> None:
        dialog = CreateBudgetDialog(
            self._current_year, self._current_month, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        if not data:
            return

        dto = CreateBudgetPeriodDTO(
            year=self._current_year,
            month=self._current_month,
            lines=[
                BudgetLineDTO(
                    category_id=item['category_id'],
                    type=item['type'],
                    amount_minor=item['amount_minor'],
                    group=item.get('group'),
                    threshold_minor=item.get('threshold_minor'),
                    sort_order=item.get('sort_order', 0),
                    note=item.get('note'),
                )
                for item in data
            ],
        )

        session = get_session()
        try:
            self._service.create_period(session, dto)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '创建失败', str(e))
        finally:
            session.close()

        self.refresh()

    # ── 操作：复制 ──

    def _on_copy(self) -> None:
        dto = CopyBudgetDTO(
            year=self._current_year,
            month=self._current_month,
        )

        session = get_session()
        try:
            self._service.copy_from_previous(session, dto)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '复制失败', str(e))
        finally:
            session.close()

        self.refresh()

    # ── 操作：添加行 ──

    def _on_add_line(self) -> None:
        if not self._current_period_id:
            return

        dialog = BudgetLineDialog(self, is_expense=True)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        if not data:
            return

        dto = BudgetLineDTO(
            category_id=data['category_id'],
            type=data['type'],
            amount_minor=data['amount_minor'],
            group=data.get('group'),
            threshold_minor=data.get('threshold_minor'),
            sort_order=data.get('sort_order', 0),
            note=data.get('note'),
        )

        session = get_session()
        try:
            self._service.add_line(session, self._current_period_id, dto)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '添加失败', str(e))
        finally:
            session.close()

        self.refresh()

    # ── 操作：编辑行 ──

    def _on_edit_line(self) -> None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, '提示', '请先选中一个预算行')
            return

        line_id = self._model.get_line_id(idx.row())
        if not line_id:
            return

        # 获取当前行数据
        dialog = BudgetLineDialog(self, is_expense=False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        data = dialog.get_data()
        if not data:
            return

        dto = UpdateBudgetLineDTO(
            category_id=data.get('category_id'),
            type=data.get('type'),
            amount_minor=data.get('amount_minor'),
            group=data.get('group'),
            threshold_minor=data.get('threshold_minor'),
            sort_order=data.get('sort_order'),
            note=data.get('note'),
        )

        session = get_session()
        try:
            self._service.update_line(session, line_id, dto)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '编辑失败', str(e))
        finally:
            session.close()

        self.refresh()

    # ── 操作：删除行 ──

    def _on_delete_line(self) -> None:
        idx = self._table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, '提示', '请先选中一个预算行')
            return

        line_id = self._model.get_line_id(idx.row())
        if not line_id:
            return

        reply = QMessageBox.question(
            self, '确认删除', '确定要删除此预算行吗？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            self._service.delete_line(session, line_id)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '删除失败', str(e))
        finally:
            session.close()

        self.refresh()

    # ── 操作：关闭/重新打开 ──

    def _on_close_period(self) -> None:
        if not self._current_period_id:
            return

        reply = QMessageBox.question(
            self, '确认关闭',
            f'关闭 {self._current_year}年{self._current_month}月预算后将不可编辑。确定？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = get_session()
        try:
            self._service.close_period(session, self._current_period_id)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '操作失败', str(e))
        finally:
            session.close()

        self.refresh()

    def _on_reopen_period(self) -> None:
        if not self._current_period_id:
            return

        session = get_session()
        try:
            self._service.reopen_period(session, self._current_period_id)
            session.commit()
        except ValueError as e:
            session.rollback()
            QMessageBox.warning(self, '操作失败', str(e))
        finally:
            session.close()

        self.refresh()


class CreateBudgetDialog(QDialog):
    """创建预算期间对话框。"""

    def __init__(
        self, year: int, month: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._year = year
        self._month = month
        self._line_data: list[dict] = []
        self.setWindowTitle(f'新建预算 — {year}年{month}月')
        self.resize(500, 450)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 提示
        tip = QLabel(
            '从下方选择分类并填写预算金额。\n'
            '未选中的分类不会纳入预算。'
        )
        tip.setStyleSheet('color: #888; font-size: 12px;')
        layout.addWidget(tip)

        # 分类选择区域（简化版：支出/收入选项卡）
        from PySide6.QtWidgets import QTabWidget

        tabs = QTabWidget()
        tabs.addTab(self._build_category_panel('expense'), '支出预算')
        tabs.addTab(self._build_category_panel('income'), '收入预算')
        layout.addWidget(tabs)

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _build_category_panel(self, cat_type: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        session = get_session()
        try:
            repo = BudgetRepository(session)
            cats = (
                repo.get_expense_categories()
                if cat_type == 'expense'
                else repo.get_income_categories()
            )
        finally:
            session.close()

        if not cats:
            label = QLabel('暂无可用分类，请先在分类管理中创建。')
            label.setStyleSheet('color: #888;')
            layout.addWidget(label)
            return widget

        # 简化：为每个分类创建一行
        for cat in cats:
            row = QHBoxLayout()
            name = QLabel(cat.name)
            name.setMinimumWidth(120)
            row.addWidget(name)

            amount = QSpinBox()
            amount.setRange(0, 99999999)
            amount.setSuffix(' 元')
            amount.setValue(0)
            amount.setObjectName(f'amount_{cat_type}_{cat.id}')
            row.addWidget(amount, 1)

            row.addWidget(QLabel('分组:'))

            group = QLineEdit()
            group.setMaximumWidth(80)
            group.setObjectName(f'group_{cat_type}_{cat.id}')
            row.addWidget(group)

            layout.addLayout(row)

        layout.addStretch()
        return widget

    def _on_accept(self) -> None:
        self._line_data = []

        for cat_type in ('expense', 'income'):
            session = get_session()
            try:
                repo = BudgetRepository(session)
                cats = (
                    repo.get_expense_categories()
                    if cat_type == 'expense'
                    else repo.get_income_categories()
                )
            finally:
                session.close()

            for i, cat in enumerate(cats):
                amount_widget = self.findChild(
                    QSpinBox, f'amount_{cat_type}_{cat.id}'
                )
                group_widget = self.findChild(
                    QLineEdit, f'group_{cat_type}_{cat.id}'
                )
                if amount_widget and amount_widget.value() > 0:
                    grp = group_widget.text().strip() if group_widget else None
                    self._line_data.append({
                        'category_id': cat.id,
                        'type': cat_type,
                        'amount_minor': amount_widget.value() * 100,
                        'group': grp if grp else None,
                        'sort_order': i,
                    })

        if not self._line_data:
            QMessageBox.warning(self, '提示', '请至少填写一个分类的预算金额')
            return

        self.accept()

    def get_data(self) -> list[dict]:
        return self._line_data


class BudgetLineDialog(QDialog):
    """预算明细行编辑对话框。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        is_expense: bool = True,
    ) -> None:
        super().__init__(parent)
        self._data: dict | None = None
        self.setWindowTitle('添加/编辑预算行')
        self.resize(400, 300)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        # 分类选择
        self._category_combo = QComboBox()
        self._type_combo = QComboBox()

        session = get_session()
        try:
            repo = BudgetRepository(session)

            for cat in repo.get_expense_categories():
                self._category_combo.addItem(
                    f'[支出] {cat.name}', cat.id
                )
            for cat in repo.get_income_categories():
                self._category_combo.addItem(
                    f'[收入] {cat.name}', cat.id
                )
        finally:
            session.close()

        layout.addRow('分类:', self._category_combo)

        # 类型
        self._type_combo.addItem('支出', 'expense')
        self._type_combo.addItem('收入', 'income')
        layout.addRow('类型:', self._type_combo)

        # 金额
        self._amount_spin = QSpinBox()
        self._amount_spin.setRange(1, 99999999)
        self._amount_spin.setSuffix(' 元')
        layout.addRow('计划金额:', self._amount_spin)

        # 分组
        self._group_edit = QLineEdit()
        layout.addRow('分组:', self._group_edit)

        # 阈值
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(0, 99999999)
        self._threshold_spin.setSuffix(' 元')
        self._threshold_spin.setSpecialValueText('无')
        layout.addRow('阈值:', self._threshold_spin)

        # 排序
        self._sort_spin = QSpinBox()
        self._sort_spin.setRange(0, 999)
        layout.addRow('排序:', self._sort_spin)

        # 备注
        self._note_edit = QLineEdit()
        layout.addRow('备注:', self._note_edit)

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def _on_accept(self) -> None:
        if self._category_combo.currentIndex() < 0:
            QMessageBox.warning(self, '提示', '请选择分类')
            return

        self._data = {
            'category_id': self._category_combo.currentData(),
            'type': self._type_combo.currentData(),
            'amount_minor': self._amount_spin.value() * 100,
            'group': self._group_edit.text().strip() or None,
            'threshold_minor': self._threshold_spin.value() * 100 or None,
            'sort_order': self._sort_spin.value(),
            'note': self._note_edit.text().strip() or None,
        }
        self.accept()

    def get_data(self) -> dict | None:
        return self._data
