"""BrokerImportService – import broker settlement files (CSV/XLSX) (P28)."""

import csv
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from mym.application.services.investment_service import InvestmentService
from mym.domain.entities.import_ import ImportIssue, ImportJob
from mym.domain.entities.audit import AuditLog
from mym.domain.enums import (
    CashFlowType,
    ImportIssueSeverity,
    ImportStatus,
    TransactionSource,
)
from mym.infrastructure.repositories.investment_repo import InvestmentRepository

logger = logging.getLogger(__name__)


@dataclass
class ParsedRow:
    """A single parsed row from a broker file."""
    row_number: int
    trade_date: date | None = None
    symbol: str = ""
    trade_type: str = ""  # buy, sell, dividend, transfer_in, transfer_out
    quantity: Decimal | None = None
    price: Decimal | None = None
    amount: Decimal | None = None
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    raw_data: dict[str, str] = field(default_factory=dict)
    hash_key: str = ""


@dataclass
class ImportPreview:
    """Preview of import before committing."""
    import_job: ImportJob | None = None
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_rows: int = 0
    valid_rows: int = 0

    @property
    def is_ok(self) -> bool:
        return len(self.errors) == 0


@dataclass
class ImportResult:
    success: bool
    import_job_id: int | None = None
    trades_imported: int = 0
    cash_flows_imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class BrokerImportService:
    """Parses and imports broker settlement files into investment records."""

    SUPPORTED_FLOW_TYPES = {
        "买入": CashFlowType.BUY,
        "卖出": CashFlowType.SELL,
        "buy": CashFlowType.BUY,
        "sell": CashFlowType.SELL,
        "股息": CashFlowType.DIVIDEND,
        "dividend": CashFlowType.DIVIDEND,
        "银证转入": CashFlowType.TRANSFER_IN,
        "银证转出": CashFlowType.TRANSFER_OUT,
        "transfer_in": CashFlowType.TRANSFER_IN,
        "transfer_out": CashFlowType.TRANSFER_OUT,
        "费用": CashFlowType.FEE,
        "fee": CashFlowType.FEE,
        "税费": CashFlowType.TAX,
        "tax": CashFlowType.TAX,
    }

    def __init__(self, session: Session, investment_service: InvestmentService | None = None) -> None:
        self._session = session
        self._repo = InvestmentRepository(session)
        self._inv_svc = investment_service or InvestmentService(session)

    def parse_csv(self, filepath: Path, investment_account_id: int) -> ImportPreview:
        """Parse a CSV broker file and return a preview."""
        preview = ImportPreview()

        if not filepath.exists():
            preview.errors.append(f"文件不存在: {filepath}")
            return preview

        try:
            with open(filepath, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except Exception as e:
            preview.errors.append(f"读取文件失败: {e}")
            return preview

        file_hash = hashlib.sha256(content.encode()).hexdigest()

        reader = csv.DictReader(content.splitlines())
        if not reader.fieldnames:
            preview.errors.append("无法解析CSV表头")
            return preview

        headers = {h.strip().lower(): h for h in reader.fieldnames}

        for row_num, raw_row in enumerate(reader, start=2):
            preview.total_rows += 1
            normalized = {k.strip().lower(): v.strip() for k, v in raw_row.items()}

            row = ParsedRow(row_number=row_num, raw_data=dict(raw_row))

            # Map fields
            date_str = normalized.get("date") or normalized.get("日期") or ""
            row.trade_date = self._parse_date(date_str)
            if not row.trade_date:
                preview.errors.append(f"第{row_num}行: 无法解析日期 '{date_str}'")
                continue

            row.symbol = (
                normalized.get("symbol") or normalized.get("代码") or
                normalized.get("证券代码", "")
            )
            if not row.symbol:
                preview.errors.append(f"第{row_num}行: 缺少证券代码")
                continue

            trade_type_raw = (
                normalized.get("type") or normalized.get("类型") or
                normalized.get("交易类型", "")
            ).lower()
            row.trade_type = self._map_trade_type(trade_type_raw)

            try:
                qty_str = normalized.get("quantity") or normalized.get("数量") or "0"
                row.quantity = Decimal(qty_str.replace(",", ""))
            except (InvalidOperation, ValueError):
                row.quantity = None

            try:
                price_str = normalized.get("price") or normalized.get("价格") or "0"
                row.price = Decimal(price_str.replace(",", ""))
            except (InvalidOperation, ValueError):
                row.price = None

            try:
                amt_str = normalized.get("amount") or normalized.get("金额") or "0"
                row.amount = Decimal(amt_str.replace(",", ""))
            except (InvalidOperation, ValueError):
                row.amount = None

            try:
                fee_str = normalized.get("fee") or normalized.get("费用") or "0"
                row.fee = Decimal(fee_str.replace(",", ""))
            except (InvalidOperation, ValueError):
                row.fee = Decimal("0")

            try:
                tax_str = normalized.get("tax") or normalized.get("税费") or "0"
                row.tax = Decimal(tax_str.replace(",", ""))
            except (InvalidOperation, ValueError):
                row.tax = Decimal("0")

            # Generate row-specific hash for dedup
            hash_input = f"{row.symbol}|{row.trade_date}|{row.trade_type}|{row.quantity}|{row.price}|{row.amount}"
            row.hash_key = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

            preview.valid_rows += 1
            preview.rows.append(row)

        # Create import job
        job = ImportJob(
            source_file=str(filepath),
            file_hash=file_hash,
            import_type="broker",
            status=ImportStatus.PREVIEWING,
            total_rows=preview.total_rows,
            success_rows=preview.valid_rows,
            error_rows=len(preview.errors),
        )
        self._session.add(job)
        self._session.flush()
        preview.import_job = job

        # Record issues
        for err in preview.errors:
            self._session.add(ImportIssue(
                import_job_id=job.id,
                severity=ImportIssueSeverity.ERROR,
                message=err,
            ))

        return preview

    def execute_import(
        self, preview: ImportPreview, investment_account_id: int
    ) -> ImportResult:
        """Execute the import: write trades and cash flows in a transaction."""
        if not preview.is_ok or not preview.import_job:
            return ImportResult(
                success=False, errors=["预览包含错误，无法导入"],
            )

        job = preview.import_job
        job.status = ImportStatus.IN_PROGRESS

        trades_count = 0
        cfs_count = 0
        skipped = 0
        seen_hashes: set[str] = set()

        for row in preview.rows:
            # Dedup check
            if row.hash_key in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(row.hash_key)

            # Ensure security exists
            sec = self._inv_svc.ensure_security(row.symbol, row.symbol)

            try:
                if row.trade_type in ("buy", "sell"):
                    from mym.domain.entities.investment import InvestmentTrade

                    if not row.quantity or not row.price or not row.amount:
                        continue

                    amount = row.quantity * row.price
                    net_amount = (
                        amount + row.fee + row.tax
                        if row.trade_type == "buy"
                        else amount - row.fee - row.tax
                    )

                    trade = InvestmentTrade(
                        investment_account_id=investment_account_id,
                        security_id=sec.id,
                        trade_date=row.trade_date,
                        trade_type=row.trade_type,
                        quantity=row.quantity,
                        price=row.price,
                        amount=amount,
                        fee=row.fee,
                        tax=row.tax,
                        net_amount=net_amount,
                        import_job_id=job.id,
                    )
                    self._repo.add_trade(trade)
                    self._session.flush()
                    trades_count += 1

                    # Cash flow
                    from mym.domain.entities.investment import InvestmentCashFlow
                    cf = InvestmentCashFlow(
                        investment_account_id=investment_account_id,
                        trade_id=trade.id,
                        flow_date=row.trade_date,
                        flow_type=CashFlowType.BUY if row.trade_type == "buy" else CashFlowType.SELL,
                        amount=-net_amount if row.trade_type == "buy" else net_amount,
                        import_job_id=job.id,
                    )
                    self._repo.add_cash_flow(cf)
                    cfs_count += 1

                elif row.trade_type in ("dividend", "transfer_in", "transfer_out", "fee", "tax"):
                    from mym.domain.entities.investment import InvestmentCashFlow
                    flow_type = self.SUPPORTED_FLOW_TYPES.get(
                        row.trade_type, CashFlowType.ADJUSTMENT
                    )
                    amt = row.amount or Decimal("0")
                    signed = amt if flow_type in (
                        CashFlowType.DIVIDEND, CashFlowType.TRANSFER_IN
                    ) else -amt

                    cf = InvestmentCashFlow(
                        investment_account_id=investment_account_id,
                        flow_date=row.trade_date,
                        flow_type=flow_type,
                        amount=signed,
                        import_job_id=job.id,
                        notes=f"导入: {row.symbol}",
                    )
                    self._repo.add_cash_flow(cf)
                    cfs_count += 1
            except Exception as e:
                logger.exception("Import row %d failed: %s", row.row_number, e)

        job.status = ImportStatus.COMPLETED
        job.success_rows = trades_count + cfs_count
        job.skipped_rows = skipped
        job.summary = f"导入 {trades_count} 笔交易, {cfs_count} 笔资金流"

        self._session.add(AuditLog(
            action="broker_import_completed",
            entity_type="ImportJob",
            entity_id=str(job.id),
            summary_after=job.summary,
            source=TransactionSource.IMPORT,
        ))
        logger.info("Broker import %d: %d trades, %d cash flows", job.id, trades_count, cfs_count)
        return ImportResult(
            success=True,
            import_job_id=job.id,
            trades_imported=trades_count,
            cash_flows_imported=cfs_count,
            skipped=skipped,
        )

    def _parse_date(self, s: str) -> date | None:
        """Try multiple date formats."""
        if not s:
            return None
        formats = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d"]
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def _map_trade_type(self, raw: str) -> str:
        raw_lower = raw.lower()
        if raw_lower in ("buy", "买入"):
            return "buy"
        if raw_lower in ("sell", "卖出"):
            return "sell"
        if raw_lower in ("dividend", "股息", "分红"):
            return "dividend"
        if raw_lower in ("transfer_in", "银证转入", "转入"):
            return "transfer_in"
        if raw_lower in ("transfer_out", "银证转出", "转出"):
            return "transfer_out"
        if raw_lower in ("fee", "费用"):
            return "fee"
        if raw_lower in ("tax", "税费"):
            return "tax"
        return "unknown"
