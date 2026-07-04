"""报表中心页面。"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym2.core.paths import get_db_path
from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.session import get_session
from mym2.services.report_service import (
    REPORT_TITLES,
    ReportColumn,
    ReportFilter,
    ReportKind,
    ReportResult,
    ReportService,
)
from mym2.ui.workers import (
    ReportExportRequest,
    ReportExportWorker,
    WorkerResult,
    start_worker,
)

logger = logging.getLogger('mym2.ui.reports_page')


def _minor_to_yuan(minor: int) -> str:
    sign = '-' if minor < 0 else ''
    val = abs(int(minor))
    return f'{sign}{val // 100}.{val % 100:02d}'


def _qdate_to_date(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


class ReportTableModel(QAbstractTableModel):
    """统一报表表格模型。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns: list[ReportColumn] = []
        self._rows: list[dict[str, Any]] = []

    def load_result(self, result: ReportResult | None) -> None:
        self.beginResetModel()
        if result is None:
            self._columns = []
            self._rows = []
        else:
            self._columns = result.columns
            self._rows = result.rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._columns)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section].title
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid():
            return None
        column = self._columns[index.column()]
        value = self._rows[index.row()].get(column.key)
        if role == Qt.ItemDataRole.DisplayRole:
            if value is None:
                return ''
            if column.kind == 'money':
                return _minor_to_yuan(int(value))
            if column.kind == 'date' and hasattr(value, 'isoformat'):
                return value.isoformat()
            if column.kind == 'percent':
                return f'{value}%'
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and column.kind in {
            'money',
            'integer',
            'percent',
        }:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None


class ReportsPage(QWidget):
    """报表中心。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = ReportService()
        self._result: ReportResult | None = None
        self._account_ids: list[str] = []
        self._category_ids: list[str] = []
        self._worker_threads: list[Any] = []
        self._setup_ui()
        self._load_filter_options()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel('报表中心')
        title.setStyleSheet('font-size: 22px; font-weight: bold; color: #fff;')
        layout.addWidget(title)

        filter_row = QHBoxLayout()
        self._kind_combo = QComboBox()
        for key, label in REPORT_TITLES.items():
            self._kind_combo.addItem(label, key)
        self._kind_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(QLabel('报表'))
        filter_row.addWidget(self._kind_combo)

        self._start_date = QDateEdit()
        self._start_date.setCalendarPopup(True)
        self._end_date = QDateEdit()
        self._end_date.setCalendarPopup(True)
        today = QDate.currentDate()
        self._start_date.setDate(QDate(today.year(), today.month(), 1))
        self._end_date.setDate(today)
        self._start_date.dateChanged.connect(self.refresh)
        self._end_date.dateChanged.connect(self.refresh)
        filter_row.addWidget(QLabel('开始'))
        filter_row.addWidget(self._start_date)
        filter_row.addWidget(QLabel('结束'))
        filter_row.addWidget(self._end_date)

        self._account_combo = QComboBox()
        self._account_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(QLabel('账户'))
        filter_row.addWidget(self._account_combo)

        self._category_combo = QComboBox()
        self._category_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(QLabel('分类'))
        filter_row.addWidget(self._category_combo)

        self._refresh_btn = QPushButton('刷新')
        self._refresh_btn.clicked.connect(self.refresh)
        filter_row.addWidget(self._refresh_btn)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        action_row = QHBoxLayout()
        self._summary_label = QLabel()
        self._summary_label.setStyleSheet('color: #ddd;')
        action_row.addWidget(self._summary_label, 1)
        self._csv_btn = QPushButton('导出 CSV')
        self._csv_btn.clicked.connect(self._on_export_csv)
        action_row.addWidget(self._csv_btn)
        self._excel_btn = QPushButton('导出 Excel')
        self._excel_btn.clicked.connect(self._on_export_excel)
        action_row.addWidget(self._excel_btn)
        self._pdf_btn = QPushButton('打印 PDF')
        self._pdf_btn.clicked.connect(self._on_export_pdf)
        action_row.addWidget(self._pdf_btn)
        layout.addLayout(action_row)

        self._scope_label = QLabel()
        self._scope_label.setWordWrap(True)
        self._scope_label.setStyleSheet('color: #aaa; font-size: 12px;')
        layout.addWidget(self._scope_label)

        self._model = ReportTableModel(self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_filter_options()
        self.refresh()

    def refresh(self) -> None:
        session = get_session()
        try:
            self._result = self._service.query(
                session,
                self._current_kind(),
                self._build_filter(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, '筛选条件无效', str(exc))
            return
        except Exception as exc:
            logger.warning('报表加载失败: %s', exc)
            QMessageBox.warning(self, '报表加载失败', str(exc))
            return
        finally:
            session.close()

        self._model.load_result(self._result)
        self._scope_label.setText(self._result.scope_note)
        self._summary_label.setText(self._format_summary(self._result))

    def _load_filter_options(self) -> None:
        try:
            session = get_session()
        except RuntimeError:
            self._set_filter_defaults()
            return
        try:
            accounts = list(session.scalars(self._account_stmt()))
            categories = list(session.scalars(self._category_stmt()))
        finally:
            session.close()

        self._account_combo.blockSignals(True)
        current_account = self._account_combo.currentData()
        self._account_combo.clear()
        self._account_combo.addItem('全部账户', '')
        for account in accounts:
            self._account_combo.addItem(account.name, account.id)
        index = self._account_combo.findData(current_account)
        self._account_combo.setCurrentIndex(index if index >= 0 else 0)
        self._account_combo.blockSignals(False)

        self._category_combo.blockSignals(True)
        current_category = self._category_combo.currentData()
        self._category_combo.clear()
        self._category_combo.addItem('全部分类', '')
        for category in categories:
            self._category_combo.addItem(category.name, category.id)
        index = self._category_combo.findData(current_category)
        self._category_combo.setCurrentIndex(index if index >= 0 else 0)
        self._category_combo.blockSignals(False)

    def _set_filter_defaults(self) -> None:
        self._account_combo.blockSignals(True)
        self._category_combo.blockSignals(True)
        self._account_combo.clear()
        self._category_combo.clear()
        self._account_combo.addItem('全部账户', '')
        self._category_combo.addItem('全部分类', '')
        self._account_combo.blockSignals(False)
        self._category_combo.blockSignals(False)

    def _build_filter(self) -> ReportFilter:
        account_id = self._account_combo.currentData()
        category_id = self._category_combo.currentData()
        return ReportFilter(
            start_date=_qdate_to_date(self._start_date.date()),
            end_date=_qdate_to_date(self._end_date.date()),
            account_ids=[account_id] if account_id else [],
            category_ids=[category_id] if category_id else [],
        )

    def _current_kind(self) -> ReportKind:
        return self._kind_combo.currentData()

    def _on_export_csv(self) -> None:
        self._export('CSV 文件 (*.csv)', 'report.csv', 'csv')

    def _on_export_excel(self) -> None:
        self._export('Excel 文件 (*.xlsx)', 'report.xlsx', 'excel')

    def _on_export_pdf(self) -> None:
        self._export('PDF 文件 (*.pdf)', 'report.pdf', 'pdf')

    def _export(self, file_filter: str, default_name: str, file_format: str) -> None:
        if self._result is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            '导出报表',
            default_name,
            file_filter,
        )
        if not path:
            return
        request = ReportExportRequest(
            db_path=str(get_db_path()),
            output_path=path,
            kind=self._current_kind(),
            filters=self._build_filter(),
            format=file_format,
        )
        worker = ReportExportWorker(request)
        thread = start_worker(
            worker,
            on_finished=self._on_export_finished,
            on_failed=self._on_export_failed,
        )
        self._worker_threads.append(thread)
        thread.finished.connect(lambda: self._worker_threads.remove(thread))

    def _on_export_finished(self, result: WorkerResult) -> None:
        QMessageBox.information(
            self,
            '导出完成',
            f'已导出 {result.row_count} 行到:\n{result.output_path}',
        )

    def _on_export_failed(self, message: str) -> None:
        QMessageBox.warning(self, '导出失败', message)

    @staticmethod
    def _format_summary(result: ReportResult) -> str:
        if not result.summary:
            return f'{len(result.rows)} 行'
        items = []
        for key, value in result.summary.items():
            if key.endswith('_minor'):
                items.append(f'{key}: {_minor_to_yuan(value)}')
            else:
                items.append(f'{key}: {value}')
        return f'{len(result.rows)} 行 | ' + ' | '.join(items)

    @staticmethod
    def _account_stmt():
        from sqlalchemy import select

        return select(Account).where(Account.is_enabled.is_(True)).order_by(Account.name)

    @staticmethod
    def _category_stmt():
        from sqlalchemy import select

        return select(Category).where(Category.is_enabled.is_(True)).order_by(Category.name)
