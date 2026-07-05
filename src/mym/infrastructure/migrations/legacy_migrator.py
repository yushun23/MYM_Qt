"""LegacyMigrator – migrates data from old .mym databases to new schema (P35-P36)."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from mym.domain.entities.account import Account
from mym.domain.entities.ai_ import ChatSession, ChatMessage
from mym.domain.entities.audit import AuditLog
from mym.domain.entities.budget import BudgetPeriod, BudgetLine
from mym.domain.entities.category import Category
from mym.domain.entities.import_ import ImportJob, ImportIssue, LegacyIdMap
from mym.domain.entities.investment import (
    InvestmentAccount, Security, InvestmentTrade, InvestmentCashFlow,
)
from mym.domain.entities.receivable import ReceivableCase, ReceivableEvent
from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import (
    AccountType, BudgetStatus, CashFlowType, CategoryType,
    ImportIssueSeverity, ImportStatus, InvestmentModuleStatus,
    ReceivableStatus, TransactionRole, TransactionSource, TransactionStatus,
)
from mym.infrastructure.migrations.legacy_scanner import (
    LegacyDataReader, LegacyScanner, ScanReport,
)

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    success: bool
    import_job_id: int | None = None
    accounts_migrated: int = 0
    categories_migrated: int = 0
    transactions_migrated: int = 0
    receivables_migrated: int = 0
    budgets_migrated: int = 0
    stock_accounts_migrated: int = 0
    stock_trades_migrated: int = 0
    chat_sessions_migrated: int = 0
    chat_messages_migrated: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=== 迁移结果 ===",
            f"状态: {'✅ 成功' if self.success else '❌ 失败'}",
            f"账户: {self.accounts_migrated}",
            f"分类: {self.categories_migrated}",
            f"流水: {self.transactions_migrated}",
            f"应收: {self.receivables_migrated}",
            f"预算: {self.budgets_migrated}",
            f"股票: {self.stock_accounts_migrated} (交易: {self.stock_trades_migrated})",
            f"AI对话: {self.chat_sessions_migrated} (消息: {self.chat_messages_migrated})",
        ]
        if self.errors:
            lines.append(f"\n错误: {len(self.errors)}")
        if self.warnings:
            lines.append(f"\n警告: {len(self.warnings)}")
        return "\n".join(lines)


class LegacyMigrator:
    """Migrates data from old .mym to new database schema.

    Reads with LegacyDataReader (read-only), writes through SQLAlchemy
    using the standard services and repositories. Creates an ImportJob
    for tracking and LegacyIdMap entries for each migrated row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._import_job_id: int | None = None
        self._id_maps: dict[str, dict[int, int]] = {}  # table -> {old_id: new_id}

    def scan(self, file_path: str | Path) -> ScanReport:
        """Scan an old .mym file and return a report."""
        scanner = LegacyScanner(file_path)
        return scanner.scan()

    def migrate(self, file_path: str | Path, sections: list[str] | None = None) -> MigrationResult:
        """Execute full or partial migration. sections: ['accounts','categories','transactions',...]."""
        result = MigrationResult(success=True)

        try:
            # Create import job
            job = ImportJob(
                source_file=str(Path(file_path).name),
                file_hash="legacy_migration",
                import_type="legacy_migration",
                status=ImportStatus.IN_PROGRESS,
                total_rows=0,
            )
            self._session.add(job)
            self._session.flush()
            self._import_job_id = job.id

            with LegacyDataReader(file_path) as reader:
                all_sections = sections or [
                    "accounts", "categories", "transactions",
                    "receivables", "budgets", "stocks", "ai",
                ]

                # Each section wrapped in a SAVEPOINT for isolation
                section_methods = [
                    ("accounts", self._migrate_accounts),
                    ("categories", self._migrate_categories),
                    ("transactions", self._migrate_transactions),
                    ("receivables", self._migrate_receivables),
                    ("budgets", self._migrate_budgets),
                    ("stocks", self._migrate_stocks),
                    ("ai", self._migrate_ai),
                ]
                for section_name, method in section_methods:
                    if section_name in all_sections:
                        try:
                            # Create savepoint for this section
                            savepoint = self._session.begin_nested()
                            method(reader, result)
                            # If we get here, section succeeded
                        except Exception as e:
                            # Rollback this section only
                            try:
                                savepoint.rollback()
                            except Exception:
                                pass
                            result.warnings.append(f"{section_name} 迁移失败: {e}")
                            logger.warning("Section %s failed: %s", section_name, e)

            # Update import job
            total = (
                result.accounts_migrated + result.categories_migrated +
                result.transactions_migrated + result.receivables_migrated +
                result.budgets_migrated + result.stock_trades_migrated +
                result.chat_sessions_migrated
            )
            job.total_rows = total
            job.success_rows = total
            job.status = ImportStatus.COMPLETED
            job.summary = result.summary()

            self._session.commit()
            result.import_job_id = job.id

        except Exception as e:
            try:
                self._session.rollback()
            except Exception:
                pass  # session may already be invalid
            logger.exception("Migration failed")
            result.success = False
            result.errors.append(str(e))
            result.import_job_id = self._import_job_id

        return result

    # ── Section Migrators ──────────────────────────────────────────────

    def _migrate_accounts(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        legacy_accounts = reader.read_accounts()
        type_map = {
            "asset": AccountType.ASSET,
            "liability": AccountType.LIABILITY,
            "receivable": AccountType.RECEIVABLE,
            "investment": AccountType.INVESTMENT_LINKED,
            "investment_linked": AccountType.INVESTMENT_LINKED,
        }

        for la in legacy_accounts:
            try:
                acct_type = type_map.get(la.account_type, AccountType.ASSET)
                acct = Account(
                    name=la.name,
                    account_type=acct_type,
                    opening_balance=la.opening_balance,
                    current_balance=la.current_balance,
                    notes=la.notes,
                )
                self._session.add(acct)
                self._session.flush()
                self._add_id_map("accounts", la.legacy_id, acct.id)
                result.accounts_migrated += 1
            except Exception as e:
                result.warnings.append(f"账户 '{la.name}' 迁移失败: {e}")

    def _migrate_categories(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        legacy_cats = reader.read_categories()
        type_map = {
            "income": CategoryType.INCOME,
            "expense": CategoryType.EXPENSE,
        }

        for lc in legacy_cats:
            try:
                cat_type = type_map.get(lc.category_type, CategoryType.EXPENSE)
                cat = Category(
                    name=lc.name,
                    category_type=cat_type,
                )
                self._session.add(cat)
                self._session.flush()
                self._add_id_map("categories", lc.legacy_id, cat.id)
                result.categories_migrated += 1
            except Exception as e:
                result.warnings.append(f"分类 '{lc.name}' 迁移失败: {e}")

    def _migrate_transactions(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        legacy_txs = reader.read_transactions()
        if not legacy_txs:
            return

        for lt in legacy_txs:
            try:
                new_acct_id = self._get_new_id("accounts", lt.account_id)
                if new_acct_id is None:
                    result.warnings.append(f"流水 {lt.legacy_id}: 账户 {lt.account_id} 未找到")
                    continue

                new_cat_id = self._get_new_id("categories", lt.category_id) if lt.category_id else None

                amt = abs(lt.amount)

                # Build double-entry lines
                lines = [
                    TransactionLine(
                        account_id=new_acct_id,
                        category_id=new_cat_id,
                        role=TransactionRole.DEBIT,
                        signed_amount=amt,
                        memo=lt.memo,
                    ),
                    TransactionLine(
                        account_id=new_acct_id,
                        category_id=new_cat_id,
                        role=TransactionRole.CREDIT,
                        signed_amount=amt,
                        memo=lt.memo,
                    ),
                ]

                tx = Transaction(
                    business_type=lt.business_type,
                    transaction_date=lt.transaction_date,
                    description=lt.description,
                    source=TransactionSource.MIGRATION,
                    status=TransactionStatus.POSTED,
                    import_job_id=self._import_job_id,
                )
                tx.lines = lines
                self._session.add(tx)
                self._session.flush()
                self._add_id_map("transactions", lt.legacy_id, tx.id)
                result.transactions_migrated += 1

            except Exception as e:
                result.warnings.append(f"流水 {lt.legacy_id} 迁移失败: {e}")

    def _migrate_receivables(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        legacy_recs = reader.read_receivables()
        if not legacy_recs:
            return

        # Create a system receivable account for migration
        from mym.domain.entities.account import Account
        from mym.domain.enums import AccountType as AT
        rec_acct = Account(
            name="应收账户(迁移)",
            account_type=AT.RECEIVABLE,
            opening_balance=Decimal("0"),
        )
        self._session.add(rec_acct)
        self._session.flush()

        status_map = {
            "pending": ReceivableStatus.PENDING,
            "partial": ReceivableStatus.PARTIALLY_RECOVERED,
            "partially_recovered": ReceivableStatus.PARTIALLY_RECOVERED,
            "recovered": ReceivableStatus.FULLY_RECOVERED,
            "fully_recovered": ReceivableStatus.FULLY_RECOVERED,
            "written_off": ReceivableStatus.WRITTEN_OFF,
        }

        for lr in legacy_recs:
            try:
                rec = ReceivableCase(
                    account_id=rec_acct.id,
                    debtor=lr.debtor,
                    total_amount=lr.amount,
                    recovered_amount=lr.recovered_amount,
                    occurrence_date=lr.lend_date or date.today(),
                    status=status_map.get(lr.status, ReceivableStatus.PENDING),
                    notes=lr.notes,
                    import_job_id=self._import_job_id,
                )
                self._session.add(rec)
                self._session.flush()

                # Migrate events
                for evt in lr.events:
                    try:
                        evt_date = date.today()
                        evt_str = evt.get("date", "")
                        if evt_str:
                            from datetime import datetime as dt
                            for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                                try:
                                    evt_date = dt.strptime(evt_str, fmt).date()
                                    break
                                except ValueError:
                                    continue

                        rec_event = ReceivableEvent(
                            case_id=rec.id,
                            event_type=evt.get("type", "recover"),
                            amount=Decimal(str(evt.get("amount", 0))),
                            event_date=evt_date,
                            notes=evt.get("notes"),
                        )
                        self._session.add(rec_event)
                    except Exception as e:
                        result.warnings.append(f"应收事件迁移失败: {e}")

                self._session.flush()
                self._add_id_map("receivables", lr.legacy_id, rec.id)
                result.receivables_migrated += 1

            except Exception as e:
                result.warnings.append(f"应收 {lr.legacy_id} 迁移失败: {e}")

    def _migrate_budgets(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        legacy_budgets = reader.read_budgets()

        for lb in legacy_budgets:
            try:
                budget_period = BudgetPeriod(
                    year=lb.year,
                    month=lb.month,
                    status=BudgetStatus(lb.status) if lb.status in ("open", "closed") else BudgetStatus.OPEN,
                    notes=f"迁移自旧账本",
                )
                self._session.add(budget_period)
                self._session.flush()

                # Migrate budget items
                for item in lb.items:
                    try:
                        raw_amt = item.get("amount", "0") if isinstance(item, dict) else "0"
                        amt = Decimal(str(raw_amt))
                        raw_cat = item.get("category", "") if isinstance(item, dict) else ""
                        raw_type = item.get("type", "expense") if isinstance(item, dict) else "expense"
                        budget_line = BudgetLine(
                            period_id=budget_period.id,
                            name=str(raw_cat),
                            planned_amount=amt,
                            budget_type=str(raw_type) if str(raw_type) in ('income', 'expense') else 'expense',
                        )
                        self._session.add(budget_line)
                    except Exception as e:
                        result.warnings.append(f"预算项迁移失败: {e}")

                self._session.flush()
                self._add_id_map("budgets", lb.legacy_id, budget_period.id)
                result.budgets_migrated += 1

            except Exception as e:
                result.warnings.append(f"预算 {lb.legacy_id} 迁移失败: {e}")

    def _migrate_stocks(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        stock_accts = reader.read_stock_accounts()
        trades = reader.read_stock_trades()

        # First migrate stock accounts
        if not stock_accts:
            return

        # Create linked asset accounts for each stock account
        for sa in stock_accts:
            linked = Account(
                name=f"{sa.name}(资金池)",
                account_type=AccountType.ASSET,
                opening_balance=sa.initial_capital,
            )
            self._session.add(linked)
            self._session.flush()
            self._add_id_map("stock_linked_accounts", sa.legacy_id, linked.id)

        for sa in stock_accts:
            try:
                linked_id = self._get_new_id("stock_linked_accounts", sa.legacy_id)
                inv_acct = InvestmentAccount(
                    name=sa.name,
                    linked_account_id=linked_id,
                    broker=sa.broker or "",
                    module_status=InvestmentModuleStatus.ENABLED,
                    initial_capital=sa.initial_capital,
                )
                self._session.add(inv_acct)
                self._session.flush()
                self._add_id_map("stocks", sa.legacy_id, inv_acct.id)
                result.stock_accounts_migrated += 1
            except Exception as e:
                result.warnings.append(f"股票账户 '{sa.name}' 迁移失败: {e}")

        # Create/ensure securities
        security_ids = {}
        for lt in trades:
            if lt.symbol not in security_ids:
                sec = Security(
                    symbol=lt.symbol,
                    name=lt.symbol,
                    market="US" if lt.symbol.isalpha() else "CN",
                )
                self._session.add(sec)
                self._session.flush()
                security_ids[lt.symbol] = sec.id

        # Then migrate trades
        for lt in trades:
            try:
                new_acct_id = self._get_new_id("stocks", lt.account_id)
                sec_id = security_ids.get(lt.symbol)
                if new_acct_id is None or sec_id is None:
                    continue

                trade = InvestmentTrade(
                    investment_account_id=new_acct_id,
                    security_id=sec_id,
                    trade_type=lt.trade_type,
                    trade_date=lt.trade_date,
                    quantity=lt.shares,
                    price=lt.price,
                    amount=lt.amount,
                    fee=lt.fee,
                    net_amount=lt.amount - lt.fee,
                    notes=lt.notes or f"迁移自旧账本",
                )
                self._session.add(trade)
                self._session.flush()
                self._add_id_map("stock_trades", lt.legacy_id, trade.id)
                result.stock_trades_migrated += 1

            except Exception as e:
                result.warnings.append(f"股票交易 {lt.legacy_id} 迁移失败: {e}")

    def _migrate_ai(self, reader: LegacyDataReader, result: MigrationResult) -> None:
        sessions = reader.read_chat_sessions()

        for ls in sessions:
            try:
                chat = ChatSession(
                    title=ls.title,
                    provider=ls.provider,
                    model=ls.model,
                    is_active=False,
                )
                self._session.add(chat)
                self._session.flush()

                for msg in ls.messages:
                    try:
                        chat_msg = ChatMessage(
                            session_id=chat.id,
                            role=msg.get("role", "user"),
                            content=msg.get("content", ""),
                        )
                        self._session.add(chat_msg)
                        result.chat_messages_migrated += 1
                    except Exception as e:
                        result.warnings.append(f"聊天消息迁移失败: {e}")

                self._session.flush()
                self._add_id_map("chat_sessions", ls.legacy_id, chat.id)
                result.chat_sessions_migrated += 1

            except Exception as e:
                result.warnings.append(f"对话 '{ls.title}' 迁移失败: {e}")

    # ── ID Mapping ───────────────────────────────────────────────────────

    def _add_id_map(self, table: str, old_id: int, new_id: int) -> None:
        """Record a mapping from old ID to new ID."""
        if table not in self._id_maps:
            self._id_maps[table] = {}
        self._id_maps[table][old_id] = new_id

        # Also persist to DB
        try:
            lm = LegacyIdMap(
                import_job_id=self._import_job_id,
                legacy_table=table,
                legacy_pk=str(old_id),
                new_table=table,
                new_id=str(new_id),
            )
            self._session.add(lm)
        except Exception:
            pass  # non-critical

    def _get_new_id(self, table: str, old_id: int | None) -> int | None:
        """Look up the new ID for an old ID."""
        if old_id is None:
            return None
        return self._id_maps.get(table, {}).get(old_id)

    def rollback_migration(self, import_job_id: int) -> bool:
        """Roll back all data from a specific migration import job."""
        try:
            job = self._session.get(ImportJob, import_job_id)
            if not job:
                return False

            # Void all migrated transactions
            txs = (
                self._session.query(Transaction)
                .where(Transaction.import_job_id == import_job_id)
                .all()
            )
            for tx in txs:
                tx.status = TransactionStatus.VOID

            # Delete migrated non-critical data
            self._session.query(LegacyIdMap).where(
                LegacyIdMap.import_job_id == import_job_id
            ).delete()

            job.status = ImportStatus.ROLLED_BACK
            self._session.commit()
            logger.info("Migration rollback complete for job %d", import_job_id)
            return True

        except Exception as e:
            self._session.rollback()
            logger.exception("Migration rollback failed")
            return False
