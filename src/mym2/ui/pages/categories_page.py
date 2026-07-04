"""分类管理页面 — QTableView + QAbstractTableModel。

支持收入、支出、系统分类的创建、编辑、启停、排序。
系统分类保护（不可修改名称/类型，不可启停）。
所有写操作通过 CategoryService。
"""

from __future__ import annotations

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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from mym2.db.models.category import Category
from mym2.db.session import get_session
from mym2.domain.enums import CategoryType
from mym2.repositories.category_repo import CategoryRepository
from mym2.services.category_service import CategoryService
from mym2.services.dto import CreateCategoryDTO, UpdateCategoryDTO

logger = logging.getLogger("mym2.ui.categories_page")

CATEGORY_TYPE_LABELS: dict[str, str] = {
    "expense": "支出",
    "income": "收入",
    "system": "系统",
}


class CategoryTableModel(QAbstractTableModel):
    """分类表格数据模型。"""

    COLUMNS = ["名称", "类型", "父分类", "排序", "颜色", "状态"]
    _data: list[dict[str, Any]]
    _raw_categories: list[Category]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = []
        self._raw_categories = []
        self._name_index: dict[str, str] = {}  # id → name

    def load_data(self, categories: list[Category]) -> None:
        """从 Category 列表加载数据。"""
        self.beginResetModel()
        self._raw_categories = categories
        self._name_index = {c.id: c.name for c in categories}
        self._data = [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "type_label": CATEGORY_TYPE_LABELS.get(c.type, c.type),
                "parent_id": c.parent_id,
                "parent_name": self._name_index.get(c.parent_id, "") if c.parent_id else "",
                "sort_order": c.sort_order,
                "color": c.color or "",
                "icon": c.icon or "",
                "is_enabled": c.is_enabled,
            }
            for c in categories
        ]
        self.endResetModel()

    def get_category(self, row: int) -> dict[str, Any] | None:
        """获取指定行的分类数据字典。"""
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
                return item["parent_name"]
            elif col == 3:
                return str(item["sort_order"])
            elif col == 4:
                return item["color"]
            elif col == 5:
                return "启用" if item["is_enabled"] else "已停用"

        elif role == Qt.ForegroundRole:
            if not item["is_enabled"]:
                return QColor("#888888")
            if item["type"] == "system":
                return QColor("#ff9900")

        elif role == Qt.UserRole:
            return item

        return None


class CategoryDialog(QDialog):
    """新建/编辑分类对话框。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        category_data: dict[str, Any] | None = None,
        categories: list[Category] | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_edit = category_data is not None
        self._is_system = bool(category_data and category_data.get("type") == "system")
        self._categories = categories or []
        self.setWindowTitle("编辑分类" if self._is_edit else "新建分类")
        self.setMinimumWidth(400)
        self._setup_ui(category_data)

    def _setup_ui(self, category_data: dict[str, Any] | None) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("分类名称")
        if self._is_system:
            self._name_edit.setReadOnly(True)
        form.addRow("名称:", self._name_edit)

        self._type_combo = QComboBox()
        for t in CategoryType:
            self._type_combo.addItem(CATEGORY_TYPE_LABELS.get(t.value, t.value), t.value)
        if self._is_system:
            self._type_combo.setEnabled(False)
        form.addRow("类型:", self._type_combo)

        self._parent_combo = QComboBox()
        self._parent_combo.addItem("(无)", None)
        for c in self._categories:
            if category_data and c.id == category_data.get("id"):
                continue
            self._parent_combo.addItem(c.name, c.id)
        if self._is_system:
            self._parent_combo.setEnabled(False)
        form.addRow("父分类:", self._parent_combo)

        self._sort_spin = QSpinBox()
        self._sort_spin.setRange(0, 9999)
        self._sort_spin.setValue(0)
        form.addRow("排序:", self._sort_spin)

        self._color_edit = QLineEdit()
        self._color_edit.setPlaceholderText("#FF5733（可选）")
        self._color_edit.setMaxLength(20)
        form.addRow("颜色:", self._color_edit)

        self._icon_edit = QLineEdit()
        self._icon_edit.setPlaceholderText("图标名（可选）")
        self._icon_edit.setMaxLength(50)
        form.addRow("图标:", self._icon_edit)

        layout.addLayout(form)

        if self._is_edit and category_data:
            self._name_edit.setText(category_data["name"])
            idx = self._type_combo.findData(category_data["type"])
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            pidx = self._parent_combo.findData(category_data.get("parent_id"))
            if pidx >= 0:
                self._parent_combo.setCurrentIndex(pidx)
            self._sort_spin.setValue(category_data.get("sort_order", 0))
            self._color_edit.setText(category_data.get("color", ""))
            self._icon_edit.setText(category_data.get("icon", ""))

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "验证失败", "分类名称不能为空")
            return

        self._result = {
            "name": name,
            "type": self._type_combo.currentData(),
            "parent_id": self._parent_combo.currentData(),
            "sort_order": self._sort_spin.value(),
            "color": self._color_edit.text().strip() or None,
            "icon": self._icon_edit.text().strip() or None,
        }
        self.accept()

    def get_data(self) -> dict[str, Any]:
        return getattr(self, "_result", {})


class CategoriesPage(QWidget):
    """分类管理页面。"""

    category_saved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._category_service = CategoryService()
        self._setup_ui()
        # 数据延迟加载：首次 showEvent 时刷新

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # 标题行
        header_layout = QHBoxLayout()
        title = QLabel("分类管理")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._show_disabled_cb = QCheckBox("显示已停用")
        self._show_disabled_cb.toggled.connect(self._on_filter_changed)
        header_layout.addWidget(self._show_disabled_cb)

        btn_new = QPushButton("+ 新建分类")
        btn_new.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: #fff; padding: 6px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #3b5de7; }"
        )
        btn_new.clicked.connect(self._on_new_category)
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

        self._source_model = CategoryTableModel(self)
        self._proxy_model = CatFilterProxy(self)
        self._proxy_model.setSourceModel(self._source_model)
        self._proxy_model.setFilterKeyColumn(-1)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._table.setModel(self._proxy_model)

        layout.addWidget(self._table)

        # 底部操作栏
        bottom_layout = QHBoxLayout()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索分类...")
        self._search_edit.textChanged.connect(self._on_filter_changed)
        bottom_layout.addWidget(self._search_edit)

        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(self._on_edit_category)
        bottom_layout.addWidget(btn_edit)

        btn_toggle = QPushButton("启停")
        btn_toggle.clicked.connect(self._on_toggle_category)
        bottom_layout.addWidget(btn_toggle)

        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)

    # ── 数据加载 ──────────────────────────────────────

    _first_show: bool = True

    def showEvent(self, event: QEvent) -> None:
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            with suppress(RuntimeError):
                self.refresh()  # Session factory 未初始化（测试模式）

    def refresh(self) -> None:
        """刷新分类列表。"""
        session = get_session()
        try:
            repo = CategoryRepository(session)
            categories = repo.get_all()
            self._source_model.load_data(categories)
            self._on_filter_changed()
        finally:
            session.close()

    def _get_categories_raw(self) -> list[Category]:
        """获取原始分类列表（用于对话框）。"""
        session = get_session()
        try:
            return CategoryRepository(session).get_all()
        finally:
            session.close()

    # ── 筛选 ──────────────────────────────────────────

    def _on_filter_changed(self) -> None:
        show_disabled = self._show_disabled_cb.isChecked()
        self._proxy_model.set_show_disabled(show_disabled)
        self._proxy_model.setFilterFixedString(self._search_edit.text().strip())
        self._proxy_model.invalidateFilter()

    # ── 操作 ──────────────────────────────────────────

    def _get_selected_category(self) -> dict[str, Any] | None:
        proxy_indexes = self._table.selectionModel().selectedRows()
        if not proxy_indexes:
            return None
        source_index = self._proxy_model.mapToSource(proxy_indexes[0])
        return self._source_model.get_category(source_index.row())

    def _on_new_category(self) -> None:
        dlg = CategoryDialog(
            self, category_data=None, categories=self._get_categories_raw()
        )
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            try:
                session = get_session()
                try:
                    dto = CreateCategoryDTO(
                        name=data["name"],
                        type=data["type"],
                        parent_id=data.get("parent_id"),
                        color=data.get("color"),
                        icon=data.get("icon"),
                        sort_order=data.get("sort_order", 0),
                    )
                    with session.begin():
                        self._category_service.create_category(session, dto)
                finally:
                    session.close()
                self.refresh()
                self.category_saved.emit()
            except ValueError as e:
                QMessageBox.warning(self, "创建失败", str(e))

    def _on_edit_category(self) -> None:
        item = self._get_selected_category()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择要编辑的分类")
            return

        if item.get("type") == "system":
            QMessageBox.warning(
                self,
                "无法编辑",
                f'"{item["name"]}" 为系统分类，不允许修改名称或类型。',
            )
            return

        dlg = CategoryDialog(
            self,
            category_data=item,
            categories=self._get_categories_raw(),
        )
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            try:
                session = get_session()
                try:
                    dto = UpdateCategoryDTO()
                    if data["name"] != item["name"]:
                        dto.name = data["name"]
                    if data["type"] != item["type"]:
                        dto.type = data["type"]
                    if data.get("parent_id") != item.get("parent_id"):
                        dto.parent_id = data.get("parent_id")
                    if data.get("sort_order") != item.get("sort_order"):
                        dto.sort_order = data.get("sort_order")
                    if data.get("color") != item.get("color"):
                        dto.color = data.get("color")
                    if data.get("icon") != item.get("icon"):
                        dto.icon = data.get("icon")

                    with session.begin():
                        self._category_service.update_category(
                            session, item["id"], dto
                        )
                finally:
                    session.close()
                self.refresh()
                self.category_saved.emit()
            except ValueError as e:
                QMessageBox.warning(self, "编辑失败", str(e))

    def _on_toggle_category(self) -> None:
        item = self._get_selected_category()
        if item is None:
            QMessageBox.information(self, "提示", "请先选择分类")
            return

        if item.get("type") == "system":
            QMessageBox.warning(
                self,
                "无法操作",
                f'"{item["name"]}" 为系统分类，不允许启停。',
            )
            return

        try:
            session = get_session()
            try:
                with session.begin():
                    if item["is_enabled"]:
                        self._category_service.disable_category(session, item["id"])
                    else:
                        self._category_service.enable_category(session, item["id"])
            finally:
                session.close()
            self.refresh()
            self.category_saved.emit()
        except ValueError as e:
            QMessageBox.warning(self, "操作失败", str(e))


class CatFilterProxy(QSortFilterProxyModel):
    """支持显示/隐藏已停用分类的代理模型。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._show_disabled = False

    def set_show_disabled(self, show: bool) -> None:
        self._show_disabled = show

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        if not self._show_disabled:
            idx = self.sourceModel().index(source_row, 0, source_parent)
            item = self.sourceModel().data(idx, Qt.UserRole)
            if item and not item.get("is_enabled", True):
                return False
        return super().filterAcceptsRow(source_row, source_parent)
