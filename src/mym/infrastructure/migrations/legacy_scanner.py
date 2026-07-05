"""LegacyScanner – read-only scanner for old .mym SQLite databases (P34)."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LegacyTableInfo:
    """Info about a table in the old database."""
    name: str
    row_count: int
    columns: list[str]


@dataclass
class LegacyAccount:
    """Account from old .mym database."""
    legacy_id: int
    name: str
    account_type: str  # asset, liability, receivable, investment
    opening_balance: Decimal = Decimal("0")
    current_balance: Decimal = Decimal("0")
    currency: str = "CNY"
    is_deleted: bool = False
    is_hidden: bool = False
    notes: str | None = None


@dataclass
class LegacyCategory:
    """Category from old .mym database."""
    legacy_id: int
    name: str
    category_type: str  # income, expense
    parent_id: int | None = None
    icon: str | None = None
    is_deleted: bool = False
    sort_order: int = 0


@dataclass
class LegacyTransaction:
    """Transaction from old .mym database."""
    legacy_id: int
    business_type: str
    transaction_date: date
    description: str | None = None
    amount: Decimal = Decimal("0")
    account_id: int = 0
    category_id: int | None = None
    source: str = "manual"
    status: str = "posted"
    memo: str | None = None
    created_at: str | None = None


@dataclass
class LegacyReceivable:
    """Receivable/lending record from old .mym database."""
    legacy_id: int
    debtor: str
    amount: Decimal
    recovered_amount: Decimal = Decimal("0")
    lend_date: date | None = None
    due_date: date | None = None
    status: str = "pending"
    notes: str | None = None
    events: list[dict] = field(default_factory=list)


@dataclass
class LegacyBudget:
    """Budget period from old .mym database."""
    legacy_id: int
    year: int
    month: int
    status: str = "open"
    items: list[dict] = field(default_factory=list)


@dataclass
class LegacyStockAccount:
    """Stock/investment account from old .mym database."""
    legacy_id: int
    name: str
    broker: str | None = None
    initial_capital: Decimal = Decimal("0")
    current_value: Decimal = Decimal("0")
    is_active: bool = True


@dataclass
class LegacyStockHolding:
    """Stock holding from old .mym database."""
    legacy_id: int
    account_id: int
    symbol: str
    name: str | None = None
    shares: Decimal = Decimal("0")
    cost_basis: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")


@dataclass
class LegacyStockTrade:
    """Stock trade from old .mym database."""
    legacy_id: int
    account_id: int
    symbol: str
    trade_type: str  # buy, sell
    trade_date: date
    shares: Decimal
    price: Decimal
    amount: Decimal
    fee: Decimal = Decimal("0")
    notes: str | None = None


@dataclass
class LegacyChatSession:
    """AI chat session from old .mym database."""
    legacy_id: int
    title: str
    provider: str = "openai"
    model: str = "gpt-4"
    created_at: str | None = None
    messages: list[dict] = field(default_factory=list)


@dataclass
class LegacySettings:
    """Settings from old .mym database."""
    language: str = "zh"
    theme: str = "light"
    currency: str = "CNY"
    backup_enabled: bool = True
    custom: dict = field(default_factory=dict)


@dataclass
class ScanReport:
    """Full scan report of an old .mym database."""
    file_path: str
    file_size_bytes: int
    db_version: str | None = None
    app_version: str | None = None
    tables: list[LegacyTableInfo] = field(default_factory=list)

    # Data counts
    account_count: int = 0
    category_count: int = 0
    transaction_count: int = 0
    receivable_count: int = 0
    budget_period_count: int = 0
    stock_account_count: int = 0
    stock_holding_count: int = 0
    stock_trade_count: int = 0
    chat_session_count: int = 0
    chat_message_count: int = 0

    # Issues
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    unmapped_tables: list[str] = field(default_factory=list)

    # Estimated migration size
    estimated_migration_rows: int = 0

    def is_migratable(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        lines = [
            f"=== .mym 扫描报告 ===",
            f"文件: {self.file_path}",
            f"大小: {self.file_size_bytes / (1024*1024):.1f} MB",
            f"DB版本: {self.db_version or '未知'}",
            f"",
            f"--- 数据概览 ---",
            f"账户: {self.account_count}",
            f"分类: {self.category_count}",
            f"流水: {self.transaction_count}",
            f"应收: {self.receivable_count}",
            f"预算: {self.budget_period_count}",
            f"股票账户: {self.stock_account_count}",
            f"股票持仓: {self.stock_holding_count}",
            f"股票交易: {self.stock_trade_count}",
            f"AI对话: {self.chat_session_count} (消息: {self.chat_message_count})",
            f"",
            f"预计迁移行数: {self.estimated_migration_rows}",
        ]
        if self.warnings:
            lines.append(f"\n--- 警告 ({len(self.warnings)}) ---")
            for w in self.warnings[:10]:
                lines.append(f"  ⚠ {w}")
        if self.errors:
            lines.append(f"\n--- 错误 ({len(self.errors)}) ---")
            for e in self.errors[:10]:
                lines.append(f"  ❌ {e}")
        return "\n".join(lines)


class LegacyScanner:
    """Read-only scanner for old .mym SQLite databases.

    NEVER modifies the old database. Opens in read-only mode and
    scans for known table structures.
    """

    # Known old table patterns (name -> expected columns)
    KNOWN_TABLES = {
        "accounts": ["id", "name", "type", "balance", "opening_balance"],
        "categories": ["id", "name", "type", "parent_id"],
        "transactions": ["id", "type", "date", "amount", "account_id", "category_id"],
        "transaction_lines": ["id", "transaction_id", "account_id", "amount"],
        "receivables": ["id", "debtor", "amount", "recovered", "status"],
        "receivable_events": ["id", "receivable_id", "type", "amount", "date"],
        "budgets": ["id", "year", "month", "status"],
        "budget_items": ["id", "budget_id", "category", "amount"],
        "stocks": ["id", "name", "broker"],
        "stock_holdings": ["id", "stock_id", "symbol", "shares", "cost"],
        "stock_trades": ["id", "stock_id", "symbol", "type", "date", "shares", "price"],
        "chat_sessions": ["id", "title", "provider", "model"],
        "chat_messages": ["id", "session_id", "role", "content"],
        "settings": ["key", "value"],
        "migrations": ["version"],
    }

    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path)
        if not self._path.exists():
            raise FileNotFoundError(f"旧账本不存在: {file_path}")
        if not self._path.suffix.lower() in (".mym", ".sqlite", ".db"):
            raise ValueError(f"不支持的文件格式: {self._path.suffix}")

    def scan(self) -> ScanReport:
        """Perform a full scan of the old database and return a report."""
        report = ScanReport(
            file_path=str(self._path),
            file_size_bytes=self._path.stat().st_size,
        )

        # Connect in read-only mode
        uri = f"file:{self._path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            report.errors.append(f"无法打开数据库: {e}")
            return report

        try:
            # Get version info
            report.db_version = self._get_db_version(conn)
            report.app_version = self._get_app_version(conn)

            # Scan tables
            tables = self._list_tables(conn)
            for table_name in tables:
                row_count = self._count_table(conn, table_name)
                columns = self._get_columns(conn, table_name)
                info = LegacyTableInfo(
                    name=table_name,
                    row_count=row_count,
                    columns=columns,
                )
                report.tables.append(info)

                if table_name not in self.KNOWN_TABLES:
                    report.unmapped_tables.append(table_name)

            # Count data by known types
            report.account_count = self._count_table(conn, "accounts")
            report.category_count = self._count_table(conn, "categories")
            report.transaction_count = self._count_table(conn, "transactions")
            report.receivable_count = self._count_table(conn, "receivables")
            report.budget_period_count = self._count_table(conn, "budgets")
            report.stock_account_count = self._count_table(conn, "stocks")
            report.stock_holding_count = self._count_table(conn, "stock_holdings")
            report.stock_trade_count = self._count_table(conn, "stock_trades")
            report.chat_session_count = self._count_table(conn, "chat_sessions")
            report.chat_message_count = self._count_table(conn, "chat_messages")

            # Estimate migration size
            report.estimated_migration_rows = (
                report.account_count + report.category_count +
                report.transaction_count + report.receivable_count +
                report.budget_period_count + report.stock_trade_count +
                report.chat_message_count
            )

            # Validate schema compatibility
            self._validate_schema(conn, report)

        finally:
            conn.close()

        return report

    def _get_db_version(self, conn: sqlite3.Connection) -> str | None:
        try:
            row = conn.execute("SELECT version FROM migrations ORDER BY version DESC LIMIT 1").fetchone()
            return str(row["version"]) if row else None
        except sqlite3.Error:
            return None

    def _get_app_version(self, conn: sqlite3.Connection) -> str | None:
        try:
            row = conn.execute("SELECT value FROM settings WHERE key='app_version'").fetchone()
            return row["value"] if row else None
        except sqlite3.Error:
            return None

    def _list_tables(self, conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [r["name"] for r in rows]

    def _count_table(self, conn: sqlite3.Connection, table: str) -> int:
        try:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM [{table}]").fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error:
            return 0

    def _get_columns(self, conn: sqlite3.Connection, table: str) -> list[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info([{table}])").fetchall()
            return [r["name"] for r in rows]
        except sqlite3.Error:
            return []

    def _validate_schema(self, conn: sqlite3.Connection, report: ScanReport) -> None:
        """Validate that known tables have expected columns."""
        for table_name, expected_cols in self.KNOWN_TABLES.items():
            actual = self._get_columns(conn, table_name)
            if not actual:
                continue  # table doesn't exist, skip

            # Check critical columns
            for col in expected_cols[:3]:  # check first 3 expected cols
                if col not in actual:
                    report.warnings.append(
                        f"表 '{table_name}' 缺少列 '{col}'，"
                        f"实际列: {actual[:5]}"
                    )
                    break

        # Check foreign keys
        try:
            fk_check = conn.execute("PRAGMA foreign_keys").fetchone()
            if fk_check and not fk_check[0]:
                report.warnings.append("外键约束未启用")
        except sqlite3.Error:
            pass

        # Integrity check
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                report.errors.append(f"数据库完整性检查失败: {result[0]}")
        except sqlite3.Error as e:
            report.errors.append(f"完整性检查失败: {e}")


class LegacyDataReader:
    """Reads data from old .mym database for migration purposes."""

    @staticmethod
    def _get(row, key, default=None):
        """Safe getter for sqlite3.Row (doesn't support .get)."""
        try:
            return row[key]
        except (KeyError, IndexError):
            return default


    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path)
        uri = f"file:{self._path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def read_accounts(self) -> list[LegacyAccount]:
        rows = self._conn.execute("SELECT * FROM accounts").fetchall()
        result = []
        for r in rows:
            try:
                result.append(LegacyAccount(
                    legacy_id=r["id"],
                    name=r["name"],
                    account_type=self._get(r, "type", "asset") or "asset",
                    opening_balance=Decimal(str(self._get(r, "opening_balance", 0) or 0)),
                    current_balance=Decimal(str(self._get(r, "balance", 0) or 0)),
                    is_deleted=bool(self._get(r, "is_deleted", 0)),
                    is_hidden=bool(self._get(r, "is_hidden", 0)),
                    notes=self._get(r, "notes"),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping account row %s: %s", dict(r) if r else "None", e)
        return result

    def read_categories(self) -> list[LegacyCategory]:
        rows = self._conn.execute("SELECT * FROM categories").fetchall()
        result = []
        for r in rows:
            try:
                result.append(LegacyCategory(
                    legacy_id=r["id"],
                    name=r["name"],
                    category_type=self._get(r, "type", "expense") or "expense",
                    parent_id=self._get(r, "parent_id"),
                    is_deleted=bool(self._get(r, "is_deleted", 0)),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping category row: %s", e)
        return result

    def read_transactions(self) -> list[LegacyTransaction]:
        rows = self._conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
        result = []
        for r in rows:
            try:
                tx_date = r["date"]
                if isinstance(tx_date, str):
                    from datetime import datetime as dt
                    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
                        try:
                            tx_date = dt.strptime(tx_date, fmt).date()
                            break
                        except ValueError:
                            continue

                amt = Decimal(str(self._get(r, "amount", 0) or 0))

                result.append(LegacyTransaction(
                    legacy_id=r["id"],
                    business_type=self._get(r, "type", "expense") or "expense",
                    transaction_date=tx_date if isinstance(tx_date, date) else date.today(),
                    description=self._get(r, "description"),
                    amount=amt,
                    account_id=self._get(r, "account_id", 0) or 0,
                    category_id=self._get(r, "category_id"),
                    source=self._get(r, "source", "manual") or "manual",
                    status=self._get(r, "status", "posted") or "posted",
                    memo=self._get(r, "memo") or self._get(r, "notes"),
                    created_at=str(self._get(r, "created_at", "")),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping transaction row: %s", e)
        return result

    def read_receivables(self) -> list[LegacyReceivable]:
        rows = self._conn.execute("SELECT * FROM receivables").fetchall()
        result = []
        for r in rows:
            try:
                rec = LegacyReceivable(
                    legacy_id=r["id"],
                    debtor=self._get(r, "debtor", "") or "",
                    amount=Decimal(str(self._get(r, "amount", 0) or 0)),
                    recovered_amount=Decimal(str(self._get(r, "recovered", 0) or 0)),
                    status=self._get(r, "status", "pending") or "pending",
                    notes=self._get(r, "notes"),
                )
                # Read events
                try:
                    evt_rows = self._conn.execute(
                        "SELECT * FROM receivable_events WHERE receivable_id=?",
                        (r["id"],)
                    ).fetchall()
                    for evt in evt_rows:
                        rec.events.append({
                            "type": self._get(evt, "type", ""),
                            "amount": str(self._get(evt, "amount", 0)),
                            "date": str(self._get(evt, "date", "")),
                            "notes": self._get(evt, "notes", ""),
                        })
                except sqlite3.Error:
                    pass
                result.append(rec)
            except (KeyError, ValueError) as e:
                logger.warning("Skipping receivable: %s", e)
        return result

    def read_budgets(self) -> list[LegacyBudget]:
        rows = self._conn.execute("SELECT * FROM budgets").fetchall()
        result = []
        for r in rows:
            try:
                budget = LegacyBudget(
                    legacy_id=r["id"],
                    year=self._get(r, "year", date.today().year) or date.today().year,
                    month=self._get(r, "month", date.today().month) or date.today().month,
                    status=self._get(r, "status", "open") or "open",
                )
                # Read budget items
                try:
                    item_rows = self._conn.execute(
                        "SELECT * FROM budget_items WHERE budget_id=?", (r["id"],)
                    ).fetchall()
                    for item in item_rows:
                        budget.items.append({
                            "category": self._get(item, "category", ""),
                            "amount": str(self._get(item, "amount", 0)),
                            "type": self._get(item, "type", "expense"),
                        })
                except sqlite3.Error:
                    pass
                result.append(budget)
            except (KeyError, ValueError) as e:
                logger.warning("Skipping budget: %s", e)
        return result

    def read_stock_accounts(self) -> list[LegacyStockAccount]:
        rows = self._conn.execute("SELECT * FROM stocks").fetchall()
        result = []
        for r in rows:
            try:
                result.append(LegacyStockAccount(
                    legacy_id=r["id"],
                    name=self._get(r, "name", "") or "",
                    broker=self._get(r, "broker"),
                    initial_capital=Decimal(str(self._get(r, "initial_capital", 0) or 0)),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping stock: %s", e)
        return result

    def read_stock_trades(self) -> list[LegacyStockTrade]:
        rows = self._conn.execute("SELECT * FROM stock_trades ORDER BY date").fetchall()
        result = []
        for r in rows:
            try:
                trade_date = r["date"]
                if isinstance(trade_date, str):
                    from datetime import datetime as dt
                    trade_date = dt.strptime(trade_date, "%Y-%m-%d").date()
                result.append(LegacyStockTrade(
                    legacy_id=r["id"],
                    account_id=self._get(r, "stock_id", 0) or 0,
                    symbol=self._get(r, "symbol", "") or "",
                    trade_type=self._get(r, "type", "buy") or "buy",
                    trade_date=trade_date if isinstance(trade_date, date) else date.today(),
                    shares=Decimal(str(self._get(r, "shares", 0) or 0)),
                    price=Decimal(str(self._get(r, "price", 0) or 0)),
                    amount=Decimal(str(self._get(r, "amount", 0) or 0)),
                    fee=Decimal(str(self._get(r, "fee", 0) or 0)),
                    notes=self._get(r, "notes"),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping trade: %s", e)
        return result

    def read_chat_sessions(self) -> list[LegacyChatSession]:
        rows = self._conn.execute("SELECT * FROM chat_sessions").fetchall()
        result = []
        for r in rows:
            try:
                session = LegacyChatSession(
                    legacy_id=r["id"],
                    title=self._get(r, "title", "旧对话") or "旧对话",
                    provider=self._get(r, "provider", "openai") or "openai",
                    model=self._get(r, "model", "gpt-4") or "gpt-4",
                    created_at=str(self._get(r, "created_at", "")),
                )
                try:
                    msg_rows = self._conn.execute(
                        "SELECT * FROM chat_messages WHERE session_id=? ORDER BY id",
                        (r["id"],)
                    ).fetchall()
                    for msg in msg_rows:
                        session.messages.append({
                            "role": self._get(msg, "role", "user"),
                            "content": self._get(msg, "content", ""),
                            "created_at": str(self._get(msg, "created_at", "")),
                        })
                except sqlite3.Error:
                    pass
                result.append(session)
            except (KeyError, ValueError) as e:
                logger.warning("Skipping chat session: %s", e)
        return result

    def read_settings(self) -> LegacySettings:
        try:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
            kv = {r["key"]: r["value"] for r in rows}
            return LegacySettings(
                language=self._get(kv, "language", "zh"),
                theme=self._get(kv, "theme", "light"),
                currency=self._get(kv, "currency", "CNY"),
                backup_enabled=self._get(kv, "backup_enabled", "1") == "1",
                custom={k: v for k, v in kv.items()
                        if k not in ("language", "theme", "currency", "backup_enabled", "app_version")},
            )
        except sqlite3.Error:
            return LegacySettings()
