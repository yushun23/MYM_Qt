"""应用主题切换。"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

DARK_STYLE = """
QMainWindow { background: #1e1f2b; }
QWidget {
    font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    color: #ddd;
}
"""

LIGHT_STYLE = """
QMainWindow { background: #f6f7fb; }
QWidget {
    font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    color: #20242a;
}
"""


def stylesheet_for(theme: str) -> str:
    """返回主题样式表。"""
    return LIGHT_STYLE if theme == 'light' else DARK_STYLE


def apply_theme(theme: str, app: QApplication | None = None) -> str:
    """应用主题并返回实际使用的主题名。"""
    normalized = 'light' if theme == 'light' else 'dark'
    target = app or QApplication.instance()
    if target is not None:
        target.setStyleSheet(stylesheet_for(normalized))
    return normalized
