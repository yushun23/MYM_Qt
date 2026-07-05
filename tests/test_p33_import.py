"""Tests for P33 – AI Financial Table Import."""

import csv
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.import_service import (
    ImportService,
    ImportField,
    FieldMapping,
    FieldDetector,
    ImportPreview,
    ImportResult,
    ImportIssue,
    ImportIssueSeverity,
    compute_row_hash,
    compute_file_hash,
    parse_date,
)
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.enums import AccountType, CategoryType
from mym.infrastructure.database.db_manager import DatabaseManager


@pytest.fixture
def db_mgr():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    yield mgr
    mgr.close()
    tmp_path.unlink(missing_ok=True)


@pytest.fixture
def session(db_mgr: DatabaseManager) -> Session:
    s = db_mgr.new_session()
    yield s
    s.close()


@pytest.fixture
def populated_session(db_mgr: DatabaseManager) -> Session:
    """Session with accounts and categories."""
    s = db_mgr.new_session()
    accts = [
        Account(name="现金", account_type=AccountType.ASSET, opening_balance=Decimal("1000")),
        Account(name="银行卡", account_type=AccountType.ASSET, opening_balance=Decimal("5000")),
    ]
    cats = [
        Category(name="餐饮", category_type=CategoryType.EXPENSE),
        Category(name="交通", category_type=CategoryType.EXPENSE),
        Category(name="工资", category_type=CategoryType.INCOME),
    ]
    s.add_all(accts + cats)
    s.commit()
    yield s
    s.close()


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestFieldDetector:
    """Test auto-detection of field mappings."""

    def test_detect_date(self):
        detector = FieldDetector()
        assert detector.detect("日期") == ImportField.DATE
        assert detector.detect("date") == ImportField.DATE

    def test_detect_amount(self):
        detector = FieldDetector()
        assert detector.detect("金额") == ImportField.AMOUNT

    def test_detect_account(self):
        detector = FieldDetector()
        assert detector.detect("账户") == ImportField.ACCOUNT

    def test_detect_category(self):
        detector = FieldDetector()
        assert detector.detect("分类") == ImportField.CATEGORY

    def test_detect_memo(self):
        detector = FieldDetector()
        assert detector.detect("备注") == ImportField.MEMO

    def test_detect_income(self):
        detector = FieldDetector()
        assert detector.detect("收入") == ImportField.INCOME_AMOUNT

    def test_detect_expense(self):
        detector = FieldDetector()
        assert detector.detect("支出") == ImportField.EXPENSE_AMOUNT

    def test_unknown_returns_none(self):
        detector = FieldDetector()
        assert detector.detect("未知字段XYZ") is None


class TestDateParsing:
    def test_iso_date(self):
        assert parse_date("2025-07-01") == date(2025, 7, 1)

    def test_slash_date(self):
        assert parse_date("2025/07/01") == date(2025, 7, 1)

    def test_chinese_date(self):
        assert parse_date("2025年07月01日") == date(2025, 7, 1)

    def test_us_date(self):
        assert parse_date("07/01/2025") == date(2025, 7, 1)

    def test_compact_date(self):
        assert parse_date("20250701") == date(2025, 7, 1)

    def test_invalid_date(self):
        assert parse_date("not-a-date") is None

    def test_none_date(self):
        assert parse_date(None) is None

    def test_already_date(self):
        d = date(2025, 7, 1)
        assert parse_date(d) == d


class TestRowHashing:
    def test_same_data_same_hash(self):
        d1 = {"date": "2025-07-01", "amount": "100"}
        d2 = {"date": "2025-07-01", "amount": "100"}
        assert compute_row_hash(d1) == compute_row_hash(d2)

    def test_different_data_different_hash(self):
        d1 = {"date": "2025-07-01", "amount": "100"}
        d2 = {"date": "2025-07-02", "amount": "100"}
        assert compute_row_hash(d1) != compute_row_hash(d2)

    def test_order_independent(self):
        d1 = {"date": "2025-07-01", "amount": "100"}
        d2 = {"amount": "100", "date": "2025-07-01"}
        assert compute_row_hash(d1) == compute_row_hash(d2)


class TestReadHeaders:
    def test_csv_headers(self, session, temp_dir):
        f = temp_dir / "test.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "备注"])

        svc = ImportService(session)
        headers = svc.read_headers(str(f))
        assert headers == ["日期", "金额", "分类", "备注"]

    def test_csv_no_data(self, session, temp_dir):
        f = temp_dir / "empty.csv"
        f.write_text("")

        svc = ImportService(session)
        headers = svc.read_headers(str(f))
        assert headers == []


class TestImportPreview:
    def test_preview_basic(self, populated_session, temp_dir):
        f = temp_dir / "data.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "账户", "备注"])
            writer.writerow(["2025-07-01", "100", "餐饮", "现金", "午餐"])
            writer.writerow(["2025-07-02", "200", "交通", "银行卡", "打车"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))

        assert preview.total_rows == 2
        assert preview.valid_rows == 2
        assert preview.duplicate_rows == 0
        assert len(preview.field_mappings) == 5

    def test_preview_duplicate(self, populated_session, temp_dir):
        f = temp_dir / "dup.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类"])
            writer.writerow(["2025-07-01", "100", "餐饮"])
            writer.writerow(["2025-07-01", "100", "餐饮"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        assert preview.duplicate_rows >= 1

    def test_preview_missing_account(self, populated_session, temp_dir):
        f = temp_dir / "missing.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "账户"])
            writer.writerow(["2025-07-01", "100", "餐饮", "支付宝"])  # not exist

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        assert len(preview.accounts_to_create) >= 1
        assert "支付宝" in preview.accounts_to_create

    def test_preview_custom_mappings(self, populated_session, temp_dir):
        f = temp_dir / "custom.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["col_a", "col_b", "col_c"])
            writer.writerow(["2025-07-01", "100", "餐饮"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f), custom_mappings={
            0: ImportField.DATE,
            1: ImportField.AMOUNT,
            2: ImportField.CATEGORY,
        })
        assert preview.field_mappings[0].target_field == ImportField.DATE
        assert preview.field_mappings[1].target_field == ImportField.AMOUNT

    def test_preview_invalid_amount(self, populated_session, temp_dir):
        f = temp_dir / "bad_amt.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类"])
            writer.writerow(["2025-07-01", "abc", "餐饮"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        assert preview.error_rows >= 1


class TestExecuteImport:
    def test_execute_success(self, populated_session, temp_dir):
        f = temp_dir / "import.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "账户", "类型", "备注"])
            writer.writerow(["2025-07-01", "100", "餐饮", "现金", "支出", "午餐"])
            writer.writerow(["2025-07-05", "5000", "工资", "银行卡", "收入", "月薪"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        result = svc.execute_import(str(f), preview)

        assert result.success
        assert result.total_imported == 2
        assert result.batch_id is not None

    def test_execute_auto_create_account(self, populated_session, temp_dir):
        f = temp_dir / "new_acct.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "账户"])
            writer.writerow(["2025-07-01", "50", "餐饮", "支付宝"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        result = svc.execute_import(str(f), preview, create_accounts=True)

        assert result.success
        assert "支付宝" in result.created_accounts

    def test_execute_missing_type_defaults(self, populated_session, temp_dir):
        f = temp_dir / "no_type.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "账户"])
            writer.writerow(["2025-07-01", "100", "餐饮", "现金"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        result = svc.execute_import(str(f), preview)
        assert result.success

    def test_rollback_batch(self, populated_session, temp_dir):
        f = temp_dir / "rollback.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["日期", "金额", "分类", "账户"])
            writer.writerow(["2025-07-01", "100", "餐饮", "现金"])

        svc = ImportService(populated_session)
        preview = svc.preview(str(f))
        result = svc.execute_import(str(f), preview)
        assert result.success

        # Now rollback
        success = svc.rollback_batch(result.batch_id)
        assert success


class TestImportIssues:
    def test_issue_severity_levels(self):
        issue = ImportIssue(row=1, severity=ImportIssueSeverity.ERROR, field="amount", message="Invalid")
        assert issue.severity == ImportIssueSeverity.ERROR

    def test_issue_serialization(self):
        issue = ImportIssue(row=5, severity=ImportIssueSeverity.WARNING, field="category", message="Missing category")
        d = {"row": issue.row, "severity": issue.severity.value, "field": issue.field, "message": issue.message}
        assert d["row"] == 5
        assert d["severity"] == "warning"


class TestFieldMapping:
    def test_field_mapping_creation(self):
        fm = FieldMapping(source_index=0, source_header="日期", target_field=ImportField.DATE)
        assert fm.source_index == 0
        assert fm.target_field == ImportField.DATE

    def test_ai_suggested_flag(self):
        fm = FieldMapping(source_index=3, source_header="未知", target_field=ImportField.IGNORE, ai_suggested=True)
        assert fm.ai_suggested
