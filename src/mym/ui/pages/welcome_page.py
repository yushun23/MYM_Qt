"""Welcome page for ledger lifecycle actions.

The page is shown before a ledger is opened. It exposes the product-level entry
points that were previously missing from the Qt shell: create, open, recent
ledgers, and legacy migration.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mym.infrastructure.app_config import AppConfig
from mym.infrastructure.i18n import I18nManager


class WelcomePage(QWidget):
    """Start page shown when no ledger is open."""

    create_ledger_requested = Signal()
    open_ledger_requested = Signal()
    migrate_legacy_requested = Signal()
    open_recent_requested = Signal(str)

    def __init__(self, config: AppConfig, i18n: I18nManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._i18n = i18n
        self._recent_list_container: QWidget | None = None
        self._recent_list_layout: QVBoxLayout | None = None
        self._setup_ui()
        self.refresh_recent_ledgers()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 32, 32, 32)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.setSpacing(18)
        scroll.setWidget(content)

        title = QLabel(self._i18n.tr("welcome.title"))
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(self._i18n.tr("welcome.subtitle"))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("font-size: 14px; color: #666; margin-bottom: 12px;")
        layout.addWidget(subtitle)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.setAlignment(Qt.AlignmentFlag.AlignCenter)

        new_btn = QPushButton(self._i18n.tr("welcome.create_ledger"))
        new_btn.setMinimumSize(160, 44)
        new_btn.clicked.connect(self.create_ledger_requested.emit)
        actions.addWidget(new_btn)

        open_btn = QPushButton(self._i18n.tr("welcome.open_ledger"))
        open_btn.setMinimumSize(160, 44)
        open_btn.clicked.connect(self.open_ledger_requested.emit)
        actions.addWidget(open_btn)

        migrate_btn = QPushButton(self._i18n.tr("welcome.migrate_legacy"))
        migrate_btn.setMinimumSize(160, 44)
        migrate_btn.clicked.connect(self.migrate_legacy_requested.emit)
        actions.addWidget(migrate_btn)

        layout.addLayout(actions)

        recent_card = QFrame()
        recent_card.setFrameShape(QFrame.Shape.StyledPanel)
        recent_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        recent_card.setMaximumWidth(760)
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(18, 18, 18, 18)
        recent_layout.setSpacing(10)

        recent_title = QLabel(self._i18n.tr("welcome.recent_ledgers"))
        recent_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        recent_layout.addWidget(recent_title)

        self._recent_list_container = QWidget()
        self._recent_list_layout = QVBoxLayout(self._recent_list_container)
        self._recent_list_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_list_layout.setSpacing(8)
        recent_layout.addWidget(self._recent_list_container)

        layout.addWidget(recent_card)
        layout.addStretch()

    def refresh_recent_ledgers(self) -> None:
        """Reload recent ledger buttons from user settings."""
        if self._recent_list_layout is None:
            return

        while self._recent_list_layout.count():
            item = self._recent_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        recent = self._config.get_recent_ledgers()
        if not recent:
            empty = QLabel(self._i18n.tr("welcome.no_recent_ledgers"))
            empty.setStyleSheet("color: #888; font-style: italic;")
            self._recent_list_layout.addWidget(empty)
            return

        for raw_path in recent[:10]:
            path = Path(raw_path)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            name = QLabel(path.name or raw_path)
            name.setMinimumWidth(160)
            row_layout.addWidget(name)

            full_path = QLabel(str(path))
            full_path.setStyleSheet("color: #777;")
            full_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(full_path, 1)

            open_btn = QPushButton(self._i18n.tr("welcome.open_recent"))
            open_btn.setEnabled(path.exists())
            open_btn.clicked.connect(lambda _checked=False, p=raw_path: self.open_recent_requested.emit(p))
            row_layout.addWidget(open_btn)

            if not path.exists():
                missing = QLabel(self._i18n.tr("welcome.recent_missing"))
                missing.setStyleSheet("color: #D32F2F;")
                row_layout.addWidget(missing)

            self._recent_list_layout.addWidget(row)
