"""AttachmentAnalysisService – safe file reading, extraction, and preview (P32)."""

import base64
import csv
import hashlib
import io
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, BinaryIO

logger = logging.getLogger(__name__)

# Size limits
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_TEXT_PREVIEW_CHARS = 5000
MAX_TABLE_ROWS_PREVIEW = 100
MAX_IMAGE_DIMENSION = 1200
THUMBNAIL_MAX_SIZE = (400, 300)

ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".xlsx", ".xls", ".docx", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
}

MIME_TO_EXT = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
}


class FileCategory(str, Enum):
    TEXT = "text"
    TABLE = "table"
    DOCUMENT = "document"
    IMAGE = "image"
    UNSUPPORTED = "unsupported"


@dataclass
class AttachmentMetadata:
    """Metadata about a processed attachment."""
    file_name: str
    file_path: str
    file_size_bytes: int
    file_hash_sha256: str
    mime_type: str
    category: FileCategory
    extraction_success: bool
    extraction_error: str | None = None
    preview_text: str | None = None
    preview_table: list[list[str]] | None = None
    preview_image_base64: str | None = None
    page_count: int | None = None
    row_count: int | None = None
    processed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def privacy_summary(self) -> str:
        """Return a sanitized summary safe to show before sending to AI."""
        parts = [
            f"文件名: {self.file_name}",
            f"类型: {self.category.value}",
            f"大小: {self._format_size()}",
        ]
        if self.page_count:
            parts.append(f"页数: {self.page_count}")
        if self.row_count:
            parts.append(f"行数: {self.row_count}")
        if self.preview_text:
            preview = self.preview_text[:200].replace("\n", " ")
            parts.append(f"预览: {preview}...")
        return " | ".join(parts)

    def _format_size(self) -> str:
        if self.file_size_bytes < 1024:
            return f"{self.file_size_bytes} B"
        elif self.file_size_bytes < 1024 * 1024:
            return f"{self.file_size_bytes / 1024:.1f} KB"
        else:
            return f"{self.file_size_bytes / (1024 * 1024):.1f} MB"


@dataclass
class AttachmentResult:
    """Result of processing an attachment."""
    success: bool
    metadata: AttachmentMetadata | None = None
    errors: list[str] = field(default_factory=list)
    requires_confirmation: bool = True


class AttachmentAnalysisService:
    """Service for reading and extracting content from user attachments.

    All file processing is local. Content is only sent to external AI
    after explicit user confirmation. No raw file bytes are permanently
    stored by default – only metadata records.
    """

    def __init__(self) -> None:
        pass

    # ── Validation ──────────────────────────────────────────────────────

    def validate_file(self, file_path: str | Path) -> list[str]:
        """Validate a file before processing. Returns list of error messages."""
        errors = []
        path = Path(file_path)

        if not path.exists():
            errors.append(f"文件不存在: {file_path}")
            return errors

        if not path.is_file():
            errors.append(f"不是文件: {file_path}")
            return errors

        ext = path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"不支持的文件类型: {ext}")
            return errors

        size = path.stat().st_size
        if size > MAX_FILE_SIZE_BYTES:
            errors.append(
                f"文件过大 ({size / (1024 * 1024):.1f} MB)，"
                f"最大支持 {MAX_FILE_SIZE_MB} MB"
            )

        return errors

    def _classify_file(self, ext: str) -> FileCategory:
        """Classify a file by extension."""
        ext = ext.lower()
        if ext in (".txt", ".md"):
            return FileCategory.TEXT
        elif ext in (".csv", ".xlsx", ".xls"):
            return FileCategory.TABLE
        elif ext in (".docx", ".pdf"):
            return FileCategory.DOCUMENT
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            return FileCategory.IMAGE
        return FileCategory.UNSUPPORTED

    def _compute_hash(self, file_path: Path) -> str:
        """Compute SHA-256 hash of file."""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()

    # ── Main Processing ─────────────────────────────────────────────────

    def process_file(self, file_path: str | Path) -> AttachmentResult:
        """Process a file and return extracted content metadata."""
        path = Path(file_path)
        errors = self.validate_file(path)
        if errors:
            return AttachmentResult(success=False, errors=errors)

        ext = path.suffix.lower()
        category = self._classify_file(ext)
        file_size = path.stat().st_size
        file_hash = self._compute_hash(path)

        meta = AttachmentMetadata(
            file_name=path.name,
            file_path=str(path),
            file_size_bytes=file_size,
            file_hash_sha256=file_hash,
            mime_type=self._guess_mime(ext),
            category=category,
            extraction_success=False,
        )

        try:
            if category == FileCategory.TEXT:
                self._extract_text(path, meta)
            elif category == FileCategory.TABLE:
                self._extract_table(path, ext, meta)
            elif category == FileCategory.DOCUMENT:
                self._extract_document(path, ext, meta)
            elif category == FileCategory.IMAGE:
                self._extract_image(path, meta)
            else:
                meta.extraction_error = "不支持的文件类型"
                return AttachmentResult(
                    success=False, metadata=meta,
                    errors=[meta.extraction_error],
                )

            meta.extraction_success = True
            return AttachmentResult(success=True, metadata=meta)

        except Exception as e:
            logger.exception("Failed to process attachment: %s", path)
            meta.extraction_error = str(e)
            return AttachmentResult(
                success=False, metadata=meta, errors=[str(e)],
            )

    # ── Extractors ──────────────────────────────────────────────────────

    def _extract_text(self, path: Path, meta: AttachmentMetadata) -> None:
        """Extract text from TXT/MD files."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read(MAX_TEXT_PREVIEW_CHARS + 1)
        except UnicodeDecodeError:
            with open(path, "r", encoding="gbk", errors="replace") as f:
                content = f.read(MAX_TEXT_PREVIEW_CHARS + 1)

        if len(content) > MAX_TEXT_PREVIEW_CHARS:
            content = content[:MAX_TEXT_PREVIEW_CHARS] + "\n...(已截断)"
        meta.preview_text = self._sanitize(content)
        meta.row_count = content.count("\n") + 1

    def _extract_table(self, path: Path, ext: str, meta: AttachmentMetadata) -> None:
        """Extract table data from CSV/XLSX/XLS files."""
        if ext == ".csv":
            self._extract_csv(path, meta)
        elif ext in (".xlsx", ".xls"):
            self._extract_excel(path, meta)

    def _extract_csv(self, path: Path, meta: AttachmentMetadata) -> None:
        rows = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i >= MAX_TABLE_ROWS_PREVIEW:
                    break
                rows.append([self._sanitize(cell) for cell in row])
        meta.preview_table = rows
        meta.row_count = len(rows)

        # Also generate text preview from CSV
        if rows:
            lines = [",".join(r) for r in rows[:20]]
            meta.preview_text = "\n".join(lines)

    def _extract_excel(self, path: Path, meta: AttachmentMetadata) -> None:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_TABLE_ROWS_PREVIEW:
                    break
                rows.append([self._sanitize(str(c) if c is not None else "") for c in row])
            meta.preview_table = rows
            meta.row_count = len(rows)
            meta.preview_text = ""
            if rows:
                lines = [" | ".join(r) for r in rows[:20]]
                meta.preview_text = "\n".join(lines)
            wb.close()
        except ImportError:
            meta.extraction_error = "缺少 openpyxl 库"
            raise
        except Exception as e:
            meta.extraction_error = f"Excel 读取失败: {e}"
            raise

    def _extract_document(self, path: Path, ext: str, meta: AttachmentMetadata) -> None:
        """Extract text from DOCX/PDF files."""
        if ext == ".docx":
            self._extract_docx(path, meta)
        elif ext == ".pdf":
            self._extract_pdf(path, meta)

    def _extract_docx(self, path: Path, meta: AttachmentMetadata) -> None:
        try:
            from docx import Document
            doc = Document(str(path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            text = "\n".join(paragraphs)
            if len(text) > MAX_TEXT_PREVIEW_CHARS:
                text = text[:MAX_TEXT_PREVIEW_CHARS] + "\n...(已截断)"
            meta.preview_text = self._sanitize(text)
            meta.page_count = len(paragraphs)
        except ImportError:
            meta.extraction_error = "缺少 python-docx 库"
            raise
        except Exception as e:
            meta.extraction_error = f"DOCX 读取失败: {e}"
            raise

    def _extract_pdf(self, path: Path, meta: AttachmentMetadata) -> None:
        try:
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                meta.page_count = len(reader.pages)
                text_parts = []
                for page in reader.pages[:10]:  # max 10 pages
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)
                text = "\n---\n".join(text_parts)
                if len(text) > MAX_TEXT_PREVIEW_CHARS:
                    text = text[:MAX_TEXT_PREVIEW_CHARS] + "\n...(已截断)"
                meta.preview_text = self._sanitize(text)
        except ImportError:
            meta.extraction_error = "缺少 PyPDF2 库"
            raise
        except Exception as e:
            meta.extraction_error = f"PDF 读取失败: {e}"
            raise

    def _extract_image(self, path: Path, meta: AttachmentMetadata) -> None:
        """Generate base64 thumbnail of image for preview."""
        try:
            from PIL import Image

            with Image.open(path) as img:
                # Convert to RGB if needed
                if img.mode in ("RGBA", "P", "LA"):
                    img = img.convert("RGB")

                # Resize if too large
                w, h = img.size
                if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
                    ratio = min(MAX_IMAGE_DIMENSION / w, MAX_IMAGE_DIMENSION / h)
                    img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

                # Create thumbnail for preview
                thumb = img.copy()
                thumb.thumbnail(THUMBNAIL_MAX_SIZE, Image.LANCZOS)

                buf = io.BytesIO()
                thumb.save(buf, format="PNG")
                meta.preview_image_base64 = base64.b64encode(buf.getvalue()).decode("ascii")
                meta.row_count = 1  # single image
                meta.preview_text = f"[图片] {path.name} ({w}x{h})"
        except ImportError:
            meta.extraction_error = "缺少 Pillow 库"
            raise
        except Exception as e:
            meta.extraction_error = f"图片读取失败: {e}"
            raise

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _guess_mime(ext: str) -> str:
        ext_map = {
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        return ext_map.get(ext, "application/octet-stream")

    @staticmethod
    def _sanitize(text: str) -> str:
        """Sanitize text: remove null bytes and control chars (except newlines/tabs)."""
        if not text:
            return ""
        # Remove null bytes
        text = text.replace("\x00", "")
        # Remove control characters except \n, \r, \t
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        return text

    def prepare_for_ai(self, meta: AttachmentMetadata) -> str:
        """Prepare extracted content for sending to AI (after user confirmation)."""
        parts = [f"=== 附件: {meta.file_name} ==="]
        if meta.preview_text:
            parts.append(meta.preview_text)
        if meta.preview_table:
            parts.append("\n--- 表格数据 ---")
            for row in meta.preview_table[:50]:  # limit rows for AI
                parts.append(" | ".join(row))
        return "\n".join(parts)
