"""AttachmentHandler – widget for file selection, preview, and AI send confirmation (P32)."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.attachment_analysis_service import (
    AttachmentAnalysisService,
    AttachmentMetadata,
    AttachmentResult,
    FileCategory,
    MAX_FILE_SIZE_MB,
    ALLOWED_EXTENSIONS,
)

logger = logging.getLogger(__name__)


class AttachmentCard(QFrame):
    """A card showing a single attachment preview with send confirmation."""

    send_requested = Signal(AttachmentMetadata)  # user confirmed send
    remove_requested = Signal()

    def __init__(self, meta: AttachmentMetadata, parent=None):
        super().__init__(parent)
        self._meta = meta
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Header row
        header = QHBoxLayout()
        name_label = QLabel(f"📎 {self._meta.file_name}")
        name_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(name_label)

        cat_labels = {
            FileCategory.TEXT: "📄 文本",
            FileCategory.TABLE: "📊 表格",
            FileCategory.DOCUMENT: "📑 文档",
            FileCategory.IMAGE: "🖼️ 图片",
        }
        cat_label = QLabel(cat_labels.get(self._meta.category, "❓"))
        cat_label.setStyleSheet("color: #666; font-size: 11px;")
        header.addWidget(cat_label)
        header.addStretch()
        layout.addLayout(header)

        # Size info
        size_mb = self._meta.file_size_bytes / (1024 * 1024)
        info = QLabel(f"大小: {size_mb:.1f} MB")
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info)

        # Preview content
        if self._meta.preview_image_base64:
            self._show_image_preview(layout)
        elif self._meta.preview_table:
            self._show_table_preview(layout)
        elif self._meta.preview_text:
            self._show_text_preview(layout)

        if self._meta.extraction_error:
            err = QLabel(f"⚠️ {self._meta.extraction_error}")
            err.setStyleSheet("color: #D32F2F; font-size: 11px;")
            err.setWordWrap(True)
            layout.addWidget(err)

        # Privacy notice
        privacy = QLabel(
            "⚠️ 隐私提示: 文件内容将发送给第三方AI模型提供商。请确认不含敏感信息。"
        )
        privacy.setStyleSheet(
            "background-color: #FFF3E0; color: #E65100; padding: 4px; "
            "border-radius: 3px; font-size: 11px;"
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        # Buttons
        btn_row = QHBoxLayout()
        send_btn = QPushButton("✓ 发送给AI分析")
        send_btn.setStyleSheet("QPushButton { background-color: #1565C0; color: white; }")
        send_btn.clicked.connect(lambda: self.send_requested.emit(self._meta))
        btn_row.addWidget(send_btn)

        remove_btn = QPushButton("✗ 移除")
        remove_btn.clicked.connect(lambda: self.remove_requested.emit())
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

    def _show_image_preview(self, layout: QVBoxLayout) -> None:
        import base64
        pixmap = QPixmap()
        pixmap.loadFromData(base64.b64decode(self._meta.preview_image_base64))
        if not pixmap.isNull():
            img_label = QLabel()
            img_label.setPixmap(pixmap.scaled(300, 200, Qt.AspectRatioMode.KeepAspectRatio))
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(img_label)

    def _show_table_preview(self, layout: QVBoxLayout) -> None:
        rows = self._meta.preview_table or []
        if not rows:
            return
        tbl = QTableWidget(min(len(rows), 5), len(rows[0]) if rows else 1)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for ri, row in enumerate(rows[:5]):
            for ci, cell in enumerate(row[:10]):
                tbl.setItem(ri, ci, QTableWidgetItem(str(cell)))
        tbl.setMaximumHeight(120)
        layout.addWidget(tbl)
        if len(rows) > 5:
            more = QLabel(f"... 共 {len(rows)} 行")
            more.setStyleSheet("color: #888; font-size: 11px;")
            layout.addWidget(more)

    def _show_text_preview(self, layout: QVBoxLayout) -> None:
        text = self._meta.preview_text or ""
        preview = text[:300].replace("\n", " ")
        label = QLabel(preview)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 11px; color: #555;")
        label.setMaximumHeight(60)
        layout.addWidget(label)


class AttachmentHandler(QWidget):
    """Widget that manages file selection, preview, and sending to AI."""

    content_ready = Signal(AttachmentMetadata, str)  # (metadata, ai_ready_text)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = AttachmentAnalysisService()
        self._attachments: list[AttachmentMetadata] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Upload button
        upload_btn = QPushButton("📎 添加附件 (文档/表格/图片)")
        upload_btn.clicked.connect(self._on_select_file)
        upload_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px; "
            "border: 1px dashed #aaa; border-radius: 4px; }"
        )
        layout.addWidget(upload_btn)

        # Allowed types hint
        ext_hint = ", ".join(sorted(ALLOWED_EXTENSIONS))
        hint = QLabel(f"支持: {ext_hint} (最大 {MAX_FILE_SIZE_MB}MB)")
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Cards scroll area
        self._cards_area = QScrollArea()
        self._cards_area.setWidgetResizable(True)
        self._cards_area.setMaximumHeight(400)
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_area.setWidget(self._cards_container)
        layout.addWidget(self._cards_area)

    def _on_select_file(self) -> None:
        ext_filter = "支持的格式 ("
        for ext in sorted(ALLOWED_EXTENSIONS):
            ext_filter += f"*{ext} "
        ext_filter += ");;所有文件 (*)"

        files, _ = QFileDialog.getOpenFileNames(
            self, "选择附件", "", ext_filter,
        )

        for file_path in files:
            result = self._service.process_file(file_path)
            if not result.success:
                QMessageBox.warning(
                    self, "文件处理失败",
                    f"无法处理 {Path(file_path).name}:\n"
                    + "\n".join(result.errors),
                )
                continue

            meta = result.metadata
            self._attachments.append(meta)
            self._add_card(meta)

    def _add_card(self, meta: AttachmentMetadata) -> None:
        card = AttachmentCard(meta)
        card.send_requested.connect(self._on_send_attachment)
        card.remove_requested.connect(lambda: self._remove_card(card, meta))
        self._cards_layout.addWidget(card)

    def _remove_card(self, card: AttachmentCard, meta: AttachmentMetadata) -> None:
        if meta in self._attachments:
            self._attachments.remove(meta)
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _on_send_attachment(self, meta: AttachmentMetadata) -> None:
        """User confirmed sending this attachment to AI."""
        ai_text = self._service.prepare_for_ai(meta)
        self.content_ready.emit(meta, ai_text)

    def clear_all(self) -> None:
        """Remove all attachment cards."""
        self._attachments.clear()
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
