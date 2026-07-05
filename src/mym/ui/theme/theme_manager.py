"""Theme system: light, dark, and system-follow modes with unified style tokens."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPalette

logger = logging.getLogger(__name__)


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


@dataclass
class ThemeColors:
    """Unified color tokens for the application."""

    # Backgrounds
    bg_primary: str = "#FFFFFF"
    bg_secondary: str = "#F5F5F5"
    bg_tertiary: str = "#E8E8E8"

    # Text
    text_primary: str = "#1A1A1A"
    text_secondary: str = "#666666"
    text_disabled: str = "#999999"

    # Accent
    accent_primary: str = "#1976D2"
    accent_hover: str = "#1565C0"
    accent_light: str = "#E3F2FD"

    # Semantic
    success: str = "#2E7D32"
    warning: str = "#ED6C02"
    error: str = "#D32F2F"
    info: str = "#0288D1"

    # Borders
    border: str = "#E0E0E0"
    border_focus: str = "#1976D2"

    # Income / Expense
    income: str = "#2E7D32"
    expense: str = "#D32F2F"

    # Chart colors
    chart_colors: list[str] = field(default_factory=lambda: [
        "#1976D2", "#388E3C", "#F57C00", "#7B1FA2",
        "#C2185B", "#00796B", "#5D4037", "#303F9F",
    ])


DARK_COLORS = ThemeColors(
    bg_primary="#1E1E1E",
    bg_secondary="#2D2D2D",
    bg_tertiary="#383838",
    text_primary="#E0E0E0",
    text_secondary="#A0A0A0",
    text_disabled="#666666",
    accent_primary="#64B5F6",
    accent_hover="#42A5F5",
    accent_light="#1A3A5C",
    success="#66BB6A",
    warning="#FFA726",
    error="#EF5350",
    info="#29B6F6",
    border="#444444",
    border_focus="#64B5F6",
    income="#66BB6A",
    expense="#EF5350",
)

_APP_STYLESHEET = """
QMainWindow {{
    background-color: {bg_primary};
}}
QLabel {{
    color: {text_primary};
}}
QMenuBar {{
    background-color: {bg_secondary};
    color: {text_primary};
    border-bottom: 1px solid {border};
}}
QMenuBar::item:selected {{
    background-color: {accent_light};
}}
QMenu {{
    background-color: {bg_secondary};
    color: {text_primary};
    border: 1px solid {border};
}}
QMenu::item:selected {{
    background-color: {accent_light};
}}
QStatusBar {{
    background-color: {bg_secondary};
    color: {text_secondary};
    border-top: 1px solid {border};
}}
QSplitter::handle {{
    background-color: {border};
}}
QScrollBar:vertical {{
    background: {bg_secondary};
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {text_disabled};
    min-height: 20px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_secondary};
}}
QTableView, QTreeView, QListView {{
    background-color: {bg_primary};
    alternate-background-color: {bg_secondary};
    color: {text_primary};
    border: 1px solid {border};
    gridline-color: {border};
}}
QHeaderView::section {{
    background-color: {bg_tertiary};
    color: {text_primary};
    border: none;
    border-bottom: 1px solid {border};
    padding: 4px 8px;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {{
    background-color: {bg_primary};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 3px;
    padding: 4px 6px;
}}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {{
    border: 1px solid {border_focus};
}}
QPushButton {{
    background-color: {accent_primary};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 16px;
}}
QPushButton:hover {{
    background-color: {accent_hover};
}}
QPushButton:pressed {{
    background-color: {accent_primary};
}}
QPushButton:disabled {{
    background-color: {text_disabled};
}}
QTabWidget::pane {{
    border: 1px solid {border};
    background-color: {bg_primary};
}}
QTabBar::tab {{
    background-color: {bg_secondary};
    color: {text_secondary};
    padding: 8px 16px;
    border: 1px solid transparent;
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background-color: {bg_primary};
    color: {accent_primary};
    border: 1px solid {border};
    border-bottom: none;
}}
QToolBar {{
    background-color: {bg_secondary};
    border-bottom: 1px solid {border};
    spacing: 4px;
}}
"""


class ThemeManager(QObject):
    """Manages application theming (Light/Dark/System)."""

    theme_changed = Signal(ThemeColors)

    def __init__(self) -> None:
        super().__init__()
        self._mode: ThemeMode = ThemeMode.LIGHT
        self._colors: ThemeColors = ThemeColors()

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def colors(self) -> ThemeColors:
        return self._colors

    def set_mode(self, mode: ThemeMode) -> None:
        """Apply a theme mode."""
        self._mode = mode
        if mode == ThemeMode.DARK:
            self._colors = DARK_COLORS
        elif mode == ThemeMode.SYSTEM:
            # For now, fallback to light; system detection requires additional work
            self._colors = ThemeColors()
        else:
            self._colors = ThemeColors()
        self.theme_changed.emit(self._colors)
        logger.info("Theme set to: %s", mode.value)

    def build_stylesheet(self) -> str:
        """Build a QSS stylesheet from current colors."""
        c = self._colors
        return _APP_STYLESHEET.format(
            bg_primary=c.bg_primary,
            bg_secondary=c.bg_secondary,
            bg_tertiary=c.bg_tertiary,
            text_primary=c.text_primary,
            text_secondary=c.text_secondary,
            text_disabled=c.text_disabled,
            accent_primary=c.accent_primary,
            accent_hover=c.accent_hover,
            accent_light=c.accent_light,
            border=c.border,
            border_focus=c.border_focus,
        )
