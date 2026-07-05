"""Common dialogs: confirm, form, toast."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def show_warning(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def show_error(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)


def confirm_action(parent: QWidget | None, title: str, message: str) -> bool:
    result = QMessageBox.question(parent, title, message,
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return result == QMessageBox.StandardButton.Yes


def confirm_dangerous(parent: QWidget | None, title: str, message: str, confirm_text: str = "") -> bool:
    """Dangerous action confirmation requiring typing confirm text."""
    if confirm_text:
        full = f"{message}\n\n请输入 \"{confirm_text}\" 确认操作:"
        text, ok = __import__("PySide6.QtWidgets").QInputDialog.getText(parent, title, full)
        return ok and text == confirm_text
    return confirm_action(parent, title, f"⚠️ {message}")
