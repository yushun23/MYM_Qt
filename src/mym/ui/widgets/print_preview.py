"""PrintPreviewDialog – QWebEngineView-based A4 print preview."""

import logging

from PySide6.QtCore import QUrl, Signal
from PySide6.QtPrintSupport import QPrintPreviewDialog
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from mym.application.services.export_service import build_print_html, build_table_html

logger = logging.getLogger(__name__)


class PrintPreviewDialog(QDialog):
    """Dialog for previewing and printing HTML-based reports.

    Usage:
        dialog = PrintPreviewDialog(
            title="月度收支报表",
            headers=["日期", "金额", "分类"],
            rows=[...],
            ledger_name="我的账本",
        )
        dialog.exec()
    """

    export_pdf_requested = Signal(str)  # emits output file path

    def __init__(
        self,
        title: str,
        headers: list[str],
        rows: list[dict],
        ledger_name: str = "—",
        page_size: str = "A4",
        orientation: str = "portrait",
        extra_meta: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._title = title
        self._headers = headers
        self._rows = rows
        self._ledger_name = ledger_name
        self._page_size = page_size
        self._orientation = orientation
        self._extra_meta = extra_meta

        self.setWindowTitle(f"打印预览 – {title}")
        self.resize(900, 700)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("纸张:"))
        self._page_combo = QComboBox()
        self._page_combo.addItems(["A4", "A3", "Letter"])
        self._page_combo.setCurrentText(self._page_size)
        self._page_combo.currentTextChanged.connect(self._rebuild)
        toolbar.addWidget(self._page_combo)

        toolbar.addWidget(QLabel("方向:"))
        self._ori_combo = QComboBox()
        self._ori_combo.addItems(["portrait", "landscape"])
        self._ori_combo.setCurrentText(self._orientation)
        self._ori_combo.currentTextChanged.connect(self._rebuild)
        toolbar.addWidget(self._ori_combo)

        toolbar.addStretch()

        self._print_btn = QPushButton("打印")
        self._print_btn.clicked.connect(self._on_print)
        toolbar.addWidget(self._print_btn)

        self._pdf_btn = QPushButton("保存PDF")
        self._pdf_btn.clicked.connect(self._on_save_pdf)
        toolbar.addWidget(self._pdf_btn)

        layout.addLayout(toolbar)

        # WebEngine preview
        self._webview = QWebEngineView()
        layout.addWidget(self._webview)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild and reload the preview HTML."""
        self._page_size = self._page_combo.currentText()
        self._orientation = self._ori_combo.currentText()

        content = build_table_html(self._headers, self._rows)
        html = build_print_html(
            title=self._title,
            content_html=content,
            ledger_name=self._ledger_name,
            page_size=self._page_size,
            orientation=self._orientation,
            extra_meta=self._extra_meta,
        )
        self._webview.setHtml(html, QUrl("about:blank"))

    def _on_print(self) -> None:
        """Open print dialog."""
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            self._webview.page().print(printer, lambda ok: None)

    def _on_save_pdf(self) -> None:
        """Save as PDF."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "保存PDF", "", "PDF文件 (*.pdf)"
        )
        if path:
            self._webview.page().printToPdf(path)
            self.export_pdf_requested.emit(path)

    def set_data(self, headers: list[str], rows: list[dict]) -> None:
        """Update data and refresh."""
        self._headers = headers
        self._rows = rows
        self._rebuild()

    def set_custom_html(self, html: str) -> None:
        """Set custom HTML content directly."""
        full_html = build_print_html(
            title=self._title,
            content_html=html,
            ledger_name=self._ledger_name,
            page_size=self._page_size,
            orientation=self._orientation,
            extra_meta=self._extra_meta,
        )
        self._webview.setHtml(full_html, QUrl("about:blank"))
