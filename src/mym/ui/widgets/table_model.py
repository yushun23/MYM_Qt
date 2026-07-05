"""Base table model for QTableView with sorting and formatting."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


@dataclass
class ColumnDef:
    """Definition of a table column."""

    key: str
    label: str
    width: int = 150
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft
    format_spec: str = ""  # e.g., ".2f" for numbers


class BaseTableModel(QAbstractTableModel):
    """Generic table model for list-based data."""

    def __init__(self, columns: list[ColumnDef], parent=None):
        super().__init__(parent)
        self._columns = columns
        self._data: list[dict[str, Any]] = []

    def column_count(self) -> int:
        return len(self._columns)

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            row = self._data[index.row()]
            col = self._columns[index.column()]
            value = row.get(col.key, "")
            if isinstance(value, Decimal) and col.format_spec:
                return format(float(value), col.format_spec)
            if isinstance(value, Decimal):
                return str(value)
            return str(value) if value is not None else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._columns[index.column()].align
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section].label
        return None

    def set_data(self, data: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._data = data
        self.endResetModel()

    def get_row(self, row: int) -> dict[str, Any] | None:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    @property
    def columns(self) -> list[ColumnDef]:
        return self._columns
