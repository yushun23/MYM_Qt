"""设置页面 + 历史归档入口。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsPage(QWidget):
    """设置 — 应用设置与历史归档入口。"""

    navigate_to = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("设置")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #fff;")
        layout.addWidget(title)

        # 历史归档入口卡片
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #252738; border-radius: 8px; padding: 16px; }"
        )
        card_layout = QVBoxLayout(card)
        card_title = QLabel("历史归档")
        card_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ddd;")
        card_layout.addWidget(card_title)

        card_desc = QLabel(
            "查看导入批次、历史证券归档摘要。\n"
            "导出归档 JSON/CSV。\n"
            "历史证券数据以只读快照保存，不提供持仓、行情等功能。"
        )
        card_desc.setStyleSheet("color: #888; font-size: 13px;")
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        btn = QPushButton("打开历史归档")
        btn.setStyleSheet(
            "QPushButton { background: #4a6cf7; color: #fff; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #3b5de7; }"
        )
        btn.clicked.connect(lambda: self.navigate_to.emit("history_archive"))
        card_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(card)
        layout.addStretch()
