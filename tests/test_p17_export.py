"""Tests for P17 – ExportService and print helpers."""

import tempfile
from pathlib import Path

import pytest

from mym.application.services.export_service import (
    ExportService,
    build_print_html,
    build_table_html,
)


class TestExportService:
    def test_sanitize_filename(self):
        assert ExportService.sanitize_filename("test/<>file") == "test___file"
        assert ExportService.sanitize_filename("normal") == "normal"

    def test_default_filename(self):
        fname = ExportService.default_filename("report", "csv")
        assert fname.startswith("report_")
        assert fname.endswith(".csv")

    def test_csv_export_empty(self):
        ok, path, msg = ExportService.export_csv([], ["col1", "col2"], prefix="test")
        assert ok
        assert path.endswith(".csv")

    def test_csv_export_with_data(self):
        rows = [{"col1": "a", "col2": "1"}, {"col1": "b", "col2": "2"}]
        ok, path, msg = ExportService.export_csv(rows, ["col1", "col2"], prefix="test")
        assert ok
        content = Path(path).read_text(encoding="utf-8-sig")
        assert "col1" in content
        assert "a" in content

    def test_xlsx_export_empty(self):
        ok, path, msg = ExportService.export_xlsx([], ["col1"], prefix="test")
        assert ok

    def test_xlsx_export_with_data(self):
        rows = [{"col1": "hello", "col2": "world"}]
        ok, path, msg = ExportService.export_xlsx(rows, ["col1", "col2"], prefix="test")
        assert ok

    def test_pdf_export(self):
        ok, path, msg = ExportService.export_pdf("<html>test</html>", prefix="test")
        assert ok

    def test_png_export(self):
        import base64
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()
        ok, path, msg = ExportService.export_png(fake_png, prefix="test")
        assert ok

    def test_png_export_with_data_url(self):
        import base64
        fake_png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode()
        data_url = f"data:image/png;base64,{fake_png}"
        ok, path, msg = ExportService.export_png(data_url, prefix="test")
        assert ok


class TestBuildPrintHtml:
    def test_basic_html(self):
        html = build_print_html("My Report", "<p>Hello</p>")
        assert "My Report" in html
        assert "<p>Hello</p>" in html
        assert "A4" in html

    def test_landscape(self):
        html = build_print_html("R", "<p></p>", orientation="landscape")
        assert "landscape" in html


class TestBuildTableHtml:
    def test_empty_table(self):
        html = build_table_html(["A", "B"], [])
        assert "<table>" in html
        assert "<th>A</th>" in html

    def test_table_with_data(self):
        html = build_table_html(["Name", "Value"], [{"Name": "X", "Value": "100"}])
        assert "X" in html
        assert "100" in html
