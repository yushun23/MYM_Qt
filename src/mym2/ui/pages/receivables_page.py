"""应收占位页面。"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ReceivablesPage(QWidget):
    """应收 — 占位。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel('应收')
        label.setStyleSheet('font-size: 24px; color: #888;')
        layout.addWidget(label)
        layout.addStretch()
