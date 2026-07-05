"""Sample plugin: Import receivable cases from CSV data."""

import csv
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from io import StringIO
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImportPreview:
    """Preview of receivable import data."""
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_count: int = 0
    valid_count: int = 0

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


class ReceivableCsvImporter:
    """Parses CSV data and validates receivable import rows."""

    REQUIRED_COLUMNS = {"debtor", "total_amount", "occurrence_date"}
    OPTIONAL_COLUMNS = {"notes", "account_name"}

    def parse_preview(self, csv_content: str) -> ImportPreview:
        """Parse CSV content and return a preview without writing to database."""
        preview = ImportPreview()

        try:
            reader = csv.DictReader(StringIO(csv_content))
        except Exception as e:
            preview.errors.append(f"CSV解析失败: {e}")
            return preview

        if not reader.fieldnames:
            preview.errors.append("CSV文件没有表头")
            return preview

        # Validate columns
        headers = {h.strip().lower() for h in reader.fieldnames}
        missing = self.REQUIRED_COLUMNS - headers
        if missing:
            preview.errors.append(f"缺少必要列: {', '.join(sorted(missing))}")
            return preview

        for row_num, row in enumerate(reader, start=2):
            preview.total_count += 1

            normalized = {k.strip().lower(): v.strip() for k, v in row.items()}

            debtor = normalized.get("debtor", "").strip()
            if not debtor:
                preview.errors.append(f"第{row_num}行: 债务人名称为空")
                continue

            amount_str = normalized.get("total_amount", "0").strip()
            try:
                amount = Decimal(amount_str)
                if amount <= 0:
                    preview.errors.append(f"第{row_num}行: 金额必须大于0")
                    continue
            except Exception:
                preview.errors.append(f"第{row_num}行: 无效金额 '{amount_str}'")
                continue

            date_str = normalized.get("occurrence_date", "").strip()
            if not date_str:
                preview.errors.append(f"第{row_num}行: 日期为空")
                continue

            preview.valid_count += 1
            preview.rows.append({
                "debtor": debtor,
                "total_amount": str(amount),
                "occurrence_date": date_str,
                "notes": normalized.get("notes", ""),
                "account_name": normalized.get("account_name", ""),
                "row_number": row_num,
            })

        return preview


# Expose the class at module level for PluginManager
def get_importer() -> ReceivableCsvImporter:
    """Factory function for the plugin's main capability."""
    return ReceivableCsvImporter()
