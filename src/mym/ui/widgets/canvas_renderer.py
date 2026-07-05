"""CanvasRenderer – renders controlled canvas JSON into PySide6 widgets (P31)."""

import json
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.financial_analysis_service import (
    CanvasResponse,
)

logger = logging.getLogger(__name__)


class MetricCardWidget(QFrame):
    """A single metric card displaying label, value, and trend."""

    clicked = Signal(str)  # emits label on click

    def __init__(self, label: str, value: str, trend: str | None = None,
                 change_pct: str | None = None, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setMinimumSize(120, 80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._label_w = QLabel(label)
        self._label_w.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self._label_w)

        self._value_w = QLabel(value)
        self._value_w.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(self._value_w)

        if trend or change_pct:
            trend_text = ""
            if trend == "up":
                trend_text = f"↑ "
            elif trend == "down":
                trend_text = f"↓ "
            if change_pct:
                trend_text += f"{change_pct}%"

            trend_label = QLabel(trend_text)
            color = "#2E7D32" if trend == "up" else "#D32F2F" if trend == "down" else "#888"
            trend_label.setStyleSheet(f"font-size: 11px; color: {color};")
            layout.addWidget(trend_label)

    def mouseReleaseEvent(self, event):
        self.clicked.emit(self._label_w.text())
        super().mouseReleaseEvent(event)


class CanvasRenderer(QWidget):
    """Renders a CanvasResponse dict into a widget hierarchy.

    No raw HTML – all content goes through Qt widgets with proper escaping.
    """

    chart_clicked = Signal(dict)  # emits chart info for drill-down

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

    def clear(self) -> None:
        """Remove all rendered widgets."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def render(self, data: dict | str) -> None:
        """Render canvas data (dict or JSON string)."""
        self.clear()

        try:
            if isinstance(data, str):
                data = json.loads(data)
        except json.JSONDecodeError:
            err = QLabel("无法解析分析数据")
            err.setStyleSheet("color: #D32F2F;")
            self._layout.addWidget(err)
            return

        errors = CanvasResponse.validate(data)
        if errors:
            err_label = QLabel("数据校验失败:\n" + "\n".join(errors))
            err_label.setStyleSheet("color: #D32F2F;")
            err_label.setWordWrap(True)
            self._layout.addWidget(err_label)
            return

        title = data.get("title", "")
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 4px;")
            title_label.setWordWrap(True)
            self._layout.addWidget(title_label)

        blocks = data.get("blocks", [])
        for block_data in blocks:
            self._render_block(block_data)

        self._layout.addStretch()

    def _render_block(self, block_data: dict) -> None:
        """Render a single canvas block."""
        block_type = block_data.get("type", "")

        if block_type == "analysis_block":
            self._render_analysis_block(block_data)
        elif block_type == "metric_card":
            self._render_metric_card(block_data)
        elif block_type == "table":
            self._render_table(block_data)
        elif block_type == "chart":
            self._render_chart_placeholder(block_data)

    def _render_analysis_block(self, data: dict) -> None:
        # Text
        if data.get("text"):
            text_label = QLabel(self._escape(data["text"]))
            text_label.setWordWrap(True)
            text_label.setStyleSheet("font-size: 13px; line-height: 1.5;")
            self._layout.addWidget(text_label)

        # Inline metric items
        items = data.get("items", [])
        if items:
            row = QHBoxLayout()
            row.setSpacing(8)
            for item_data in items:
                card = MetricCardWidget(
                    label=self._escape(item_data.get("label", "")),
                    value=self._escape(item_data.get("value", "")),
                    trend=item_data.get("trend"),
                    change_pct=item_data.get("change_pct"),
                )
                row.addWidget(card)
            self._layout.addLayout(row)

        # Table
        if data.get("table"):
            tbl = self._build_table(data["table"])
            self._layout.addWidget(tbl)

        # Chart
        if data.get("chart"):
            self._render_chart_placeholder(data["chart"])

    def _render_metric_card(self, data: dict) -> None:
        card = MetricCardWidget(
            label=self._escape(data.get("label", "")),
            value=self._escape(data.get("value", "")),
            trend=data.get("trend"),
            change_pct=data.get("change_pct"),
        )
        self._layout.addWidget(card)

    def _render_table(self, data: dict) -> None:
        tbl = self._build_table(data)
        self._layout.addWidget(tbl)

    def _render_chart_placeholder(self, data: dict) -> None:
        """Render a chart placeholder that shows chart type and key data.

        For full ECharts rendering, this delegates to ChartHost when embedded
        in a QWebEngineView context. Here we show a styled summary.
        """
        chart_type = data.get("chart_type", "bar")
        title = data.get("title", "")
        labels = data.get("labels", [])
        series = data.get("series", [])

        frame = QFrame()
        frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        frame.setMinimumHeight(150)
        layout = QVBoxLayout(frame)

        header = QLabel(f"📊 {self._escape(title)} ({chart_type})")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        # Show summary data as compact table
        if labels and series:
            tbl = QTableWidget(len(labels) + 1, len(series) + 1)
            tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            tbl.horizontalHeader().setVisible(False)
            tbl.verticalHeader().setVisible(False)

            # Header row
            tbl.setItem(0, 0, QTableWidgetItem("类别"))
            for si, s in enumerate(series):
                tbl.setItem(0, si + 1, QTableWidgetItem(self._escape(s.get("name", ""))))

            for li, label in enumerate(labels[:20]):
                tbl.setItem(li + 1, 0, QTableWidgetItem(self._escape(str(label))))
                for si, s in enumerate(series):
                    data_vals = s.get("data", [])
                    val = data_vals[li] if li < len(data_vals) else ""
                    tbl.setItem(li + 1, si + 1, QTableWidgetItem(str(val)))

            tbl.resizeColumnsToContents()
            tbl.setMaximumHeight(300)
            layout.addWidget(tbl)

        self._layout.addWidget(frame)

    def _build_table(self, data: dict) -> QTableWidget:
        """Build a QTableWidget from canvas table data."""
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        title = data.get("title", "")

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        if title:
            title_label = QLabel(self._escape(title))
            title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
            container_layout.addWidget(title_label)

        tbl = QTableWidget(len(rows), len(columns))
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setHorizontalHeaderLabels([self._escape(c) for c in columns])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                tbl.setItem(ri, ci, QTableWidgetItem(self._escape(str(cell))))

        container_layout.addWidget(tbl)
        return container

    @staticmethod
    def _escape(text: str) -> str:
        """Escape text for safe display in widgets."""
        if not text:
            return ""
        # Remove any HTML-like tags
        import re
        text = re.sub(r"<[^>]*>", "", text)
        return text
