"""历史归档页面 — 只读查看。

提供导入批次列表、历史证券归档摘要查看、导出归档 JSON/CSV。
绝不提供持仓、行情、买卖、证券月结功能。
"""

from __future__ import annotations

import csv
import json
import logging
from contextlib import suppress
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    Qt,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from mym2.db.models.import_run import ImportRun
from mym2.db.models.legacy import LegacyArchiveRecord
from mym2.db.session import get_session

logger = logging.getLogger("mym2.ui.history_archive_page")


class ImportRunTableModel(QAbstractTableModel):
    """导入批次表格模型。"""

    COLUMNS = ["来源", "状态", "导入数", "跳过数", "失败数", "开始时间", "完成时间"]
    _data: list[dict[str, Any]]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = []

    def load_data(self, runs: list[ImportRun]) -> None:
        self.beginResetModel()
        self._data = [
            {
                "id": r.id,
                "source": r.source,
                "status": r.status,
                "status_label": {
                    "dry_run": "试运行",
                    "completed": "已完成",
                    "failed": "失败",
                    "rolled_back": "已回滚",
                }.get(r.status, r.status),
                "rows_imported": r.rows_imported,
                "rows_skipped": r.rows_skipped,
                "rows_failed": r.rows_failed,
                "started_at": str(r.started_at) if r.started_at else "",
                "finished_at": str(r.finished_at) if r.finished_at else "",
                "report_json": r.report_json,
            }
            for r in runs
        ]
        self.endResetModel()

    def get_run(self, row: int) -> dict[str, Any] | None:
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
            cols = [
                item["source"],
                item["status_label"],
                str(item["rows_imported"]),
                str(item["rows_skipped"]),
                str(item["rows_failed"]),
                item["started_at"],
                item["finished_at"],
            ]
            return cols[col]

        elif role == Qt.UserRole:
            return item

        return None


class ArchiveRecordTableModel(QAbstractTableModel):
    """归档记录表格模型。"""

    COLUMNS = ["旧表名", "旧记录 ID", "摘要"]
    _data: list[dict[str, Any]]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = []

    def load_data(self, records: list[LegacyArchiveRecord]) -> None:
        self.beginResetModel()
        self._data = [
            {
                "id": r.id,
                "source_table": r.source_table,
                "legacy_id": r.legacy_id,
                "summary": r.summary or "",
                "data_json": r.data_json,
            }
            for r in records
        ]
        self.endResetModel()

    def get_record(self, row: int) -> dict[str, Any] | None:
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
                return item["source_table"]
            elif col == 1:
                return item["legacy_id"]
            elif col == 2:
                return item["summary"]

        elif role == Qt.UserRole:
            return item

        return None


class JsonViewDialog(QDialog):
    """JSON 数据查看对话框（只读）。"""

    def __init__(
        self, parent: QWidget | None, title: str, json_str: str
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 400)
        layout = QVBoxLayout(self)

        text = QTextEdit()
        text.setReadOnly(True)
        try:
            parsed = json.loads(json_str)
            text.setPlainText(json.dumps(parsed, ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            text.setPlainText(json_str)
        text.setStyleSheet(
            "QTextEdit { background: #1e1f2b; color: #ddd; font-family: monospace; }"
        )
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class HistoryArchivePage(QWidget):
    """历史归档页面 — 只读查看导入批次与归档记录。

    规格：
    - 仅查看导入批次、历史证券归档摘要、导出归档 JSON/CSV
    - 绝不提供持仓、行情、买卖、证券月结功能
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        # 数据延迟加载：首次 showEvent 时刷新

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # 标题
        title = QLabel("历史归档")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        layout.addWidget(title)

        note = QLabel(
            "本页面仅提供历史归档数据查看与导出。"
            "不提供持仓、行情、买卖、证券月结等股票功能。"
            "历史证券相关数据以只读快照形式保存。"
        )
        note.setStyleSheet("color: #888; font-size: 12px; margin-bottom: 8px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Tab 分页
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #3a3d50; background: #252738; }"
            "QTabBar::tab { background: #2b2d3e; color: #aaa; padding: 6px 16px; "
            "border: none; }"
            "QTabBar::tab:selected { background: #4a6cf7; color: #fff; }"
        )

        # Tab 1: 导入批次
        self._import_tab = QWidget()
        self._setup_import_tab()
        self._tabs.addTab(self._import_tab, "导入批次")

        # Tab 2: 归档记录
        self._archive_tab = QWidget()
        self._setup_archive_tab()
        self._tabs.addTab(self._archive_tab, "归档记录")

        layout.addWidget(self._tabs)

    def _setup_import_tab(self) -> None:
        layout = QVBoxLayout(self._import_tab)
        layout.setContentsMargins(8, 8, 8, 8)

        self._import_table = QTableView()
        self._import_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._import_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._import_table.setAlternatingRowColors(True)
        self._import_table.horizontalHeader().setStretchLastSection(True)
        self._import_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._import_table.verticalHeader().setVisible(False)
        self._import_table.setStyleSheet(
            "QTableView { background: #252738; alternate-background-color: #2a2d40; "
            "gridline-color: #3a3d50; color: #ddd; }"
            "QTableView::item:selected { background: #4a6cf7; }"
            "QHeaderView::section { background: #2b2d3e; color: #aaa; "
            "padding: 4px; border: none; }"
        )
        self._import_model = ImportRunTableModel(self)
        self._import_table.setModel(self._import_model)
        layout.addWidget(self._import_table)

        btn_layout = QHBoxLayout()
        btn_view = QPushButton("查看报告")
        btn_view.clicked.connect(self._on_view_report)
        btn_layout.addWidget(btn_view)

        btn_export = QPushButton("导出归档 JSON")
        btn_export.clicked.connect(self._on_export_archive_json)
        btn_layout.addWidget(btn_export)

        btn_export_csv = QPushButton("导出归档 CSV")
        btn_export_csv.clicked.connect(self._on_export_archive_csv)
        btn_layout.addWidget(btn_export_csv)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def _setup_archive_tab(self) -> None:
        layout = QVBoxLayout(self._archive_tab)
        layout.setContentsMargins(8, 8, 8, 8)

        self._archive_table = QTableView()
        self._archive_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._archive_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._archive_table.setAlternatingRowColors(True)
        self._archive_table.horizontalHeader().setStretchLastSection(True)
        self._archive_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._archive_table.verticalHeader().setVisible(False)
        self._archive_table.setStyleSheet(
            "QTableView { background: #252738; alternate-background-color: #2a2d40; "
            "gridline-color: #3a3d50; color: #ddd; }"
            "QTableView::item:selected { background: #4a6cf7; }"
            "QHeaderView::section { background: #2b2d3e; color: #aaa; "
            "padding: 4px; border: none; }"
        )
        self._archive_model = ArchiveRecordTableModel(self)
        self._archive_table.setModel(self._archive_model)
        layout.addWidget(self._archive_table)

        btn_layout = QHBoxLayout()
        btn_detail = QPushButton("查看详情")
        btn_detail.clicked.connect(self._on_view_record_detail)
        btn_layout.addWidget(btn_detail)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    # ── 数据加载 ──────────────────────────────────────

    _first_show: bool = True

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            with suppress(RuntimeError):
                self.refresh()  # Session factory 未初始化（测试模式）

    def refresh(self) -> None:
        """刷新数据。"""
        session = get_session()
        try:
            # 导入批次
            runs = list(
                session.scalars(
                    select(ImportRun).order_by(ImportRun.started_at.desc())
                )
            )
            self._import_model.load_data(runs)

            # 归档记录
            records = list(
                session.scalars(
                    select(LegacyArchiveRecord).order_by(
                        LegacyArchiveRecord.source_table,
                        LegacyArchiveRecord.legacy_id,
                    )
                )
            )
            self._archive_model.load_data(records)
        finally:
            session.close()

    # ── 操作 ──────────────────────────────────────────

    def _get_selected_import(self) -> dict[str, Any] | None:
        indexes = self._import_table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self._import_model.get_run(indexes[0].row())

    def _get_selected_record(self) -> dict[str, Any] | None:
        indexes = self._archive_table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self._archive_model.get_record(indexes[0].row())

    def _on_view_report(self) -> None:
        item = self._get_selected_import()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择导入批次")
            return
        report = item.get("report_json", "")
        if not report:
            QMessageBox.information(self, "提示", "该批次没有详细报告")
            return
        dlg = JsonViewDialog(self, "导入报告", report)
        dlg.exec()

    def _on_view_record_detail(self) -> None:
        item = self._get_selected_record()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择归档记录")
            return
        dlg = JsonViewDialog(
            self,
            f"归档详情 — {item['source_table']}#{item['legacy_id']}",
            item.get("data_json", "{}"),
        )
        dlg.exec()

    def _on_export_archive_json(self) -> None:
        """导出归档记录为 JSON 文件。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出归档 JSON", "archive_export.json", "JSON 文件 (*.json)"
        )
        if not path:
            return

        session = get_session()
        try:
            records = list(
                session.scalars(
                    select(LegacyArchiveRecord).order_by(
                        LegacyArchiveRecord.source_table,
                        LegacyArchiveRecord.legacy_id,
                    )
                )
            )
            export_data = []
            for r in records:
                try:
                    parsed = json.loads(r.data_json)
                except json.JSONDecodeError:
                    parsed = {"raw": r.data_json}
                export_data.append({
                    "source_table": r.source_table,
                    "legacy_id": r.legacy_id,
                    "summary": r.summary,
                    "data": parsed,
                })

            with open(path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)

            msg = f"已导出 {len(export_data)} 条记录到:\n{path}"
            QMessageBox.information(self, "导出完成", msg)
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
        finally:
            session.close()

    def _on_export_archive_csv(self) -> None:
        """导出归档记录为 CSV 文件。"""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出归档 CSV", "archive_export.csv", "CSV 文件 (*.csv)"
        )
        if not path:
            return

        session = get_session()
        try:
            records = list(
                session.scalars(
                    select(LegacyArchiveRecord).order_by(
                        LegacyArchiveRecord.source_table,
                        LegacyArchiveRecord.legacy_id,
                    )
                )
            )
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["旧表名", "旧记录 ID", "摘要", "归档数据"])
                for r in records:
                    writer.writerow([r.source_table, r.legacy_id, r.summary or "", r.data_json])

            QMessageBox.information(self, "导出完成", f"已导出 {len(records)} 条记录到:\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
        finally:
            session.close()
