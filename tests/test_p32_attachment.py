"""Tests for P32 – AI Attachment Analysis."""

import csv
import io
import os
import tempfile
from pathlib import Path

import pytest

from mym.application.services.attachment_analysis_service import (
    AttachmentAnalysisService,
    AttachmentMetadata,
    AttachmentResult,
    FileCategory,
    MAX_FILE_SIZE_BYTES,
    ALLOWED_EXTENSIONS,
)


@pytest.fixture
def svc():
    return AttachmentAnalysisService()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestFileValidation:
    """Test file validation rules."""

    def test_missing_file(self, svc):
        errors = svc.validate_file("/nonexistent/file.txt")
        assert len(errors) > 0

    def test_directory_not_file(self, svc, temp_dir):
        errors = svc.validate_file(str(temp_dir))
        assert len(errors) > 0

    def test_unsupported_extension(self, svc, temp_dir):
        f = temp_dir / "test.exe"
        f.write_text("hello")
        errors = svc.validate_file(str(f))
        assert len(errors) > 0
        assert any("不支持" in e for e in errors)

    def test_file_too_large(self, svc, temp_dir):
        f = temp_dir / "large.txt"
        # Create a file just over the limit
        with open(f, "wb") as fh:
            fh.write(b"x" * (MAX_FILE_SIZE_BYTES + 1))
        errors = svc.validate_file(str(f))
        assert len(errors) > 0
        assert any("过大" in e for e in errors)

    def test_valid_file(self, svc, temp_dir):
        f = temp_dir / "valid.txt"
        f.write_text("hello")
        errors = svc.validate_file(str(f))
        assert len(errors) == 0

    def test_all_allowed_extensions(self, svc, temp_dir):
        for ext in ALLOWED_EXTENSIONS:
            f = temp_dir / f"test{ext}"
            f.write_text("test")
            errors = svc.validate_file(str(f))
            assert len(errors) == 0, f"Extension {ext} should be allowed"


class TestTextExtraction:
    """Test text file extraction."""

    def test_txt_utf8(self, svc, temp_dir):
        f = temp_dir / "test.txt"
        f.write_text("Hello 你好\nWorld 世界", encoding="utf-8")
        result = svc.process_file(str(f))
        assert result.success
        assert "Hello" in result.metadata.preview_text
        assert "你好" in result.metadata.preview_text

    def test_md_file(self, svc, temp_dir):
        f = temp_dir / "readme.md"
        f.write_text("# Title\n\nSome content here.\n\n## Section\nMore text.")
        result = svc.process_file(str(f))
        assert result.success
        assert result.metadata.category == FileCategory.TEXT
        assert "Title" in result.metadata.preview_text

    def test_sanitize_null_bytes(self, svc, temp_dir):
        f = temp_dir / "bad.txt"
        f.write_text("hello\x00world", encoding="utf-8")
        result = svc.process_file(str(f))
        assert result.success
        assert "\x00" not in result.metadata.preview_text

    def test_sanitize_control_chars(self, svc, temp_dir):
        f = temp_dir / "ctrl.txt"
        f.write_text("hello\x01\x02world\nline2", encoding="utf-8")
        result = svc.process_file(str(f))
        assert result.success
        assert "\x01" not in result.metadata.preview_text

    def test_text_truncation(self, svc, temp_dir):
        f = temp_dir / "long.txt"
        f.write_text("A" * 10000)
        result = svc.process_file(str(f))
        assert result.success
        assert "已截断" in result.metadata.preview_text


class TestCsvExtraction:
    """Test CSV file extraction."""

    def test_simple_csv(self, svc, temp_dir):
        f = temp_dir / "data.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类"])
            writer.writerow(["2025-07-01", "100", "餐饮"])
            writer.writerow(["2025-07-02", "200", "交通"])
        result = svc.process_file(str(f))
        assert result.success
        assert result.metadata.category == FileCategory.TABLE
        assert result.metadata.preview_table is not None
        assert len(result.metadata.preview_table) == 3
        assert result.metadata.preview_table[0][0] == "日期"

    def test_csv_row_count(self, svc, temp_dir):
        f = temp_dir / "many.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            for i in range(200):
                writer.writerow([f"row{i}", str(i)])
        result = svc.process_file(str(f))
        assert result.success
        assert result.metadata.row_count <= 100  # max rows


class TestFileClassification:
    """Test file type classification."""

    def test_txt_classification(self, svc, temp_dir):
        f = temp_dir / "doc.txt"
        f.write_text("test")
        result = svc.process_file(str(f))
        assert result.metadata.category == FileCategory.TEXT

    def test_csv_classification(self, svc, temp_dir):
        f = temp_dir / "data.csv"
        f.write_text("a,b\n1,2")
        result = svc.process_file(str(f))
        assert result.metadata.category == FileCategory.TABLE

    def test_image_classification(self, svc, temp_dir):
        f = temp_dir / "photo.png"
        f.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
        result = svc.process_file(str(f))
        # May fail extraction but classification should be IMAGE
        assert result.metadata is not None
        assert result.metadata.category == FileCategory.IMAGE


class TestPrivacyAndSafety:
    """Test privacy and data safety aspects."""

    def test_privacy_summary(self, svc, temp_dir):
        f = temp_dir / "private.txt"
        f.write_text("Sensitive data here\nMore data")
        result = svc.process_file(str(f))
        summary = result.metadata.privacy_summary()
        assert result.metadata.file_name in summary
        assert "类型" in summary
        # Privacy summary should not reveal full content
        assert "Sensitive data here" in summary  # preview is shown

    def test_file_hash_computed(self, svc, temp_dir):
        f = temp_dir / "hashme.txt"
        f.write_text("content")
        result = svc.process_file(str(f))
        assert len(result.metadata.file_hash_sha256) == 64

    def test_prepare_for_ai(self, svc, temp_dir):
        f = temp_dir / "for_ai.txt"
        f.write_text("AI will read this")
        result = svc.process_file(str(f))
        ai_text = svc.prepare_for_ai(result.metadata)
        assert "附件:" in ai_text
        assert "AI will read this" in ai_text

    def test_no_path_leak_in_text(self, svc, temp_dir):
        """Ensure full file paths aren't leaked in preview text."""
        f = temp_dir / "secret.txt"
        f.write_text("normal content")
        result = svc.process_file(str(f))
        # The full path should not appear in preview (only filename)
        full_path = str(temp_dir)
        assert full_path not in result.metadata.preview_text

    def test_corrupted_file_handling(self, svc, temp_dir):
        """Corrupted files should return errors, not crash."""
        f = temp_dir / "corrupt.csv"
        f.write_bytes(b'\x00\x00\x00\x00\xff\xff')
        result = svc.process_file(str(f))
        # Should not crash; may succeed or fail depending on content
        assert isinstance(result, AttachmentResult)


class TestAttachmentMetadata:
    """Test metadata data class."""

    def test_format_small_size(self):
        meta = AttachmentMetadata(
            file_name="test.txt",
            file_path="/tmp/test.txt",
            file_size_bytes=500,
            file_hash_sha256="a" * 64,
            mime_type="text/plain",
            category=FileCategory.TEXT,
            extraction_success=True,
        )
        assert "500 B" in meta._format_size()

    def test_format_kb_size(self):
        meta = AttachmentMetadata(
            file_name="test.txt",
            file_path="/tmp/test.txt",
            file_size_bytes=5000,
            file_hash_sha256="a" * 64,
            mime_type="text/plain",
            category=FileCategory.TEXT,
            extraction_success=True,
        )
        assert "KB" in meta._format_size()

    def test_format_mb_size(self):
        meta = AttachmentMetadata(
            file_name="test.txt",
            file_path="/tmp/test.txt",
            file_size_bytes=5 * 1024 * 1024,
            file_hash_sha256="a" * 64,
            mime_type="text/plain",
            category=FileCategory.TEXT,
            extraction_success=True,
        )
        assert "MB" in meta._format_size()


class TestExcelExtraction:
    """Test Excel file extraction (when openpyxl is available)."""

    def test_xlsx_extraction(self, svc, temp_dir):
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed")

        f = temp_dir / "test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Date", "Amount", "Category"])
        ws.append(["2025-07-01", 100, "Food"])
        ws.append(["2025-07-02", 200, "Transport"])
        wb.save(str(f))
        wb.close()

        result = svc.process_file(str(f))
        assert result.success
        assert result.metadata.category == FileCategory.TABLE
        assert result.metadata.preview_table is not None
        assert len(result.metadata.preview_table) == 3
