"""迁移执行器 — 真正的数据迁移执行引擎。"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from mym2.db.engine import create_mym2_engine
from mym2.db.ensure_schema import ensure_budget_columns
from mym2.db.migrate import upgrade_to_head
from mym2.db.models.account import Account
from mym2.db.models.app_setting import AppSetting
from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.db.models.import_run import ImportRun
from mym2.db.models.legacy import LegacyArchiveRecord, LegacyIdMap
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import (
    AccountType,
    CategoryType,
    TransactionType,
    is_asset_account,
)
from mym2.importers.legacy_mym.mapper import LegacyMapper
from mym2.importers.legacy_mym.migration_plan import MigrationPlan
from mym2.importers.legacy_mym.source_reader import SourceReader
from mym2.importers.legacy_mym.validators import (
    convert_amount_to_minor,
    is_settings_allowed,
    map_account_type,
    map_transaction_type,
)

logger = logging.getLogger('mym2.importers.legacy_mym.executor')


class MigrationExecutor:
    """迁移执行器。"""

    def __init__(
        self,
        source_path: str | Path,
        target_db_path: str | Path,
        *,
        stock_strategy: str = 'historical_snapshot',
    ) -> None:
        self._source_path = Path(source_path).resolve()
        self._target_db_path = Path(target_db_path).resolve()
        self._stock_strategy = stock_strategy
        self._source_hash: str = ''
        self._plan: MigrationPlan | None = None
        self._import_run_id: str = ''
        self._legacy_id_maps: list[tuple[str, str, str, str]] = []
        self._stats = {
            'accounts_imported': 0, 'categories_imported': 0,
            'transactions_imported': 0, 'budget_periods_imported': 0,
            'budget_lines_imported': 0, 'settings_imported': 0,
            'archived': 0, 'skipped': 0, 'failed': 0,
        }

    def execute(self, *, backup: bool = True) -> dict:
        self._pre_check()
        with SourceReader(self._source_path) as reader:
            self._source_hash = reader.file_hash_before or ''
            mapper = LegacyMapper(reader, stock_strategy=self._stock_strategy)
            self._plan = mapper.build_plan()
            self._plan.generated_at = MigrationPlan.utc_now_iso()
            self._plan.source_path = str(self._source_path)
            self._plan.source_hash = self._source_hash
            self._plan.stock_strategy = self._stock_strategy
            legacy_data = self._read_legacy_data(reader)

        self._check_duplicate_import()

        backup_path: Path | None = None
        if backup and self._target_db_path.exists():
            backup_path = self._backup_target_db()

        upgrade_to_head(self._target_db_path)
        engine = create_mym2_engine(self._target_db_path)
        ensure_budget_columns(engine)
        try:
            with engine.begin() as conn:
                session = Session(bind=conn)
                self._do_migrate(session, legacy_data)
            verification = self._verify_migration()
            return self._generate_report(verification, backup_path)
        except Exception:
            logger.exception('迁移失败，事务已回滚')
            if backup_path and backup_path.exists():
                logger.info('备份保留在: %s', backup_path)
            raise
        finally:
            engine.dispose()

    def dry_run_plan(self) -> MigrationPlan:
        with SourceReader(self._source_path) as reader:
            self._source_hash = reader.file_hash_before or ''
            mapper = LegacyMapper(reader, stock_strategy=self._stock_strategy)
            plan = mapper.build_plan()
            plan.generated_at = MigrationPlan.utc_now_iso()
            plan.source_path = str(self._source_path)
            plan.source_hash = self._source_hash
            plan.stock_strategy = self._stock_strategy
            return plan

    def _pre_check(self) -> None:
        if not self._source_path.exists():
            raise FileNotFoundError(f'旧账套文件不存在: {self._source_path}')
        self._target_db_path.parent.mkdir(parents=True, exist_ok=True)

    def _check_duplicate_import(self) -> None:
        if not self._target_db_path.exists():
            return
        try:
            with open(self._target_db_path, 'rb') as f:
                header = f.read(16)
            if header != b'SQLite format 3\x00':
                return
        except Exception:
            return

        engine = create_mym2_engine(self._target_db_path)
        try:
            with Session(engine) as session:
                existing = session.scalars(
                    select(ImportRun).where(
                        ImportRun.source.like(f'%{self._source_hash[:16]}%'),
                        ImportRun.status == 'completed',
                    )
                ).first()
                if existing is not None:
                    raise ValueError(
                        f'该旧账套（SHA-256: {self._source_hash[:16]}...）'
                        f'已导入过（ImportRun: {existing.id}）。'
                        f'如需重新导入，请先创建新的目标数据库。'
                    )
        finally:
            engine.dispose()

    def _backup_target_db(self) -> Path:
        backup_dir = self._target_db_path.parent / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).replace(tzinfo=None).strftime('%Y%m%d_%H%M%S')
        backup_path = backup_dir / f'mym2_backup_{ts}.db'
        src = sqlite3.connect(str(self._target_db_path))
        dst = sqlite3.connect(str(backup_path))
        src.backup(dst)
        src.close()
        dst.close()
        logger.info('目标数据库已备份到: %s', backup_path)
        return backup_path

    def _read_legacy_data(self, reader: SourceReader) -> dict[str, list[dict]]:
        data: dict[str, list[dict]] = {}
        for tbl in ('accounts', 'categories', 'transactions',
                     'budget_months', 'budget_items', 'budget_lines'):
            try:
                rows = reader.fetch_all(f'SELECT * FROM {tbl} ORDER BY id')
                data[tbl] = [dict(r) for r in rows]
            except Exception:
                data[tbl] = []
        try:
            rows = reader.fetch_all('SELECT key, value FROM settings')
            data['settings'] = [dict(r) for r in rows]
        except Exception:
            data['settings'] = []
        for tbl in ('stock_accounts', 'stock_cash_flows', 'stock_trades',
                     'stock_quotes', 'stock_symbols', 'stock_settlement_imports',
                     'stock_monthly_settlements', 'stock_module_meta'):
            try:
                rows = reader.fetch_all(f'SELECT * FROM {tbl} ORDER BY id')
                if rows:
                    data[tbl] = [dict(r) for r in rows]
            except Exception:
                pass
        for tbl in ('ai_chat_messages', 'ai_imported_records'):
            try:
                rows = reader.fetch_all(f'SELECT * FROM {tbl} ORDER BY id')
                if rows:
                    data[tbl] = [dict(r) for r in rows]
            except Exception:
                pass
        return data

    def _do_migrate(
        self, session: Session, legacy_data: dict[str, list[dict]]
    ) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        self._import_run_id = str(uuid.uuid4())
        import_run = ImportRun(
            id=self._import_run_id,
            source=f'migration:{self._source_hash}',
            status='in_progress', rows_imported=0,
            rows_skipped=0, rows_failed=0, started_at=now,
        )
        session.add(import_run)
        session.flush()
        try:
            acct_map = self._migrate_accounts(
                session, legacy_data.get('accounts', []))
            cat_map = self._migrate_categories(
                session, legacy_data.get('categories', []))
            stxs = self._generate_settlement_transactions(acct_map)
            self._migrate_transactions(
                session, legacy_data.get('transactions', []),
                acct_map, cat_map, stxs)
            pmap = self._migrate_budget_periods(
                session, legacy_data.get('budget_months', []))
            self._migrate_budget_lines(
                session, legacy_data.get('budget_lines', []),
                pmap, cat_map)
            self._migrate_settings(
                session, legacy_data.get('settings', []))
            if self._stock_strategy != 'skip':
                self._archive_stock_data(session, legacy_data)
            self._archive_ai_data(session, legacy_data)
            self._write_legacy_id_maps(session)
            self._recalculate_all_balances(session)
            import_run.status = 'completed'
            import_run.rows_imported = (
                self._stats['accounts_imported']
                + self._stats['categories_imported']
                + self._stats['transactions_imported']
                + self._stats['budget_periods_imported']
                + self._stats['budget_lines_imported']
                + self._stats['settings_imported']
                + self._stats['archived']
            )
            import_run.rows_skipped = self._stats['skipped']
            import_run.rows_failed = self._stats['failed']
            import_run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            session.flush()
        except Exception:
            import_run.status = 'failed'
            import_run.finished_at = datetime.now(UTC).replace(tzinfo=None)
            session.flush()
            raise

    def _migrate_accounts(
        self, session: Session, rows: list[dict]
    ) -> dict[int, str]:
        account_map: dict[int, str] = {}
        for row in rows:
            try:
                legacy_id = int(row['id'])
                name = str(row.get('name') or '')
                old_type = str(row.get('type') or 'Asset')
                is_linked = legacy_id in self._get_linked_ids()
                if is_linked and self._stock_strategy == 'skip':
                    self._stats['skipped'] += 1
                    continue
                if is_linked and self._stock_strategy == 'historical_snapshot':
                    new_type = AccountType.INVESTMENT_SNAPSHOT
                    is_editable, is_locked_val = False, True
                else:
                    mapped = map_account_type(old_type)
                    new_type = mapped if mapped else AccountType.CASH
                    is_editable = True
                    is_locked_val = bool(row.get('is_system_locked', 0))
                bal = convert_amount_to_minor(row.get('balance', 0)).minor
                opening = convert_amount_to_minor(
                    row.get('opening_balance', 0)).minor
                new_id = str(uuid.uuid4())
                account = Account(
                    id=new_id, name=name, type=new_type,
                    group=str(row.get('group_name') or ''),
                    is_enabled=bool(row.get('is_active', 1)),
                    opening_balance_minor=opening,
                    current_balance_minor=bal,
                    is_locked=is_locked_val, is_editable=is_editable,
                    currency='CNY',
                )
                session.add(account)
                account_map[legacy_id] = new_id
                self._add_legacy_map(
                    'accounts', str(legacy_id), 'accounts', new_id)
                self._stats['accounts_imported'] += 1
            except Exception as e:
                self._stats['failed'] += 1
                logger.warning('账户 %s 迁移失败: %s', row.get('id'), e)
        session.flush()
        return account_map

    def _migrate_categories(
        self, session: Session, rows: list[dict]
    ) -> dict[int, str]:
        category_map: dict[int, str] = {}
        for row in rows:
            try:
                legacy_id = int(row['id'])
                name = str(row.get('name') or '')
                old_type = str(row.get('type') or 'Expense')
                if old_type.lower() in ('expense',):
                    new_type = CategoryType.EXPENSE
                elif old_type.lower() in ('income',):
                    new_type = CategoryType.INCOME
                else:
                    new_type = CategoryType.SYSTEM
                new_id = str(uuid.uuid4())
                category = Category(
                    id=new_id, name=name, type=new_type,
                    is_enabled=bool(row.get('is_active', 1)), sort_order=0,
                )
                session.add(category)
                category_map[legacy_id] = new_id
                self._add_legacy_map(
                    'categories', str(legacy_id), 'categories', new_id)
                self._stats['categories_imported'] += 1
            except Exception as e:
                self._stats['failed'] += 1
                logger.warning('分类 %s 迁移失败: %s', row.get('id'), e)
        session.flush()
        return category_map

    def _migrate_transactions(
        self, session: Session, rows: list[dict],
        account_map: dict[int, str], category_map: dict[int, str],
        settlement_txs: list[dict],
    ) -> None:
        for stx in settlement_txs:
            self._insert_transaction(session, stx)
        for row in rows:
            try:
                old_type = str(row.get('trans_type') or '')
                new_type = map_transaction_type(old_type)
                if new_type is None:
                    new_type = TransactionType.EXPENSE
                amt = convert_amount_to_minor(row.get('amount', 0)).minor
                old_out = row.get('account_out_id')
                old_in = row.get('account_in_id')
                old_cat = row.get('category_id')
                new_out = account_map.get(old_out) if old_out else None
                new_in = account_map.get(old_in) if old_in else None
                new_cat = category_map.get(old_cat) if old_cat else None
                if new_out is None:
                    self._stats['skipped'] += 1
                    continue
                dt_raw = row.get('trans_date')
                if isinstance(dt_raw, str):
                    tx_date = self._parse_date(dt_raw)
                elif dt_raw:
                    tx_date = self._parse_date(str(dt_raw))
                else:
                    tx_date = date(2000, 1, 1)
                tx_data = {
                    'transaction_date': tx_date,
                    'type': str(new_type),
                    'category_id': new_cat,
                    'account_out_id': new_out,
                    'account_in_id': new_in,
                    'amount_minor': amt,
                    'note': str(row.get('note') or ''),
                    'source': 'import',
                    'is_locked': False,
                    'is_cleared': bool(row.get('is_cleared', 0)),
                    'legacy_id': row['id'],
                }
                self._insert_transaction(session, tx_data)
            except Exception as e:
                self._stats['failed'] += 1
                logger.warning('流水 %s 迁移失败: %s', row.get('id'), e)

    def _insert_transaction(
        self, session: Session, tx_data: dict
    ) -> None:
        new_id = str(uuid.uuid4())
        tx = Transaction(
            id=new_id,
            transaction_date=tx_data['transaction_date'],
            type=str(tx_data['type']),
            category_id=tx_data.get('category_id'),
            account_out_id=tx_data['account_out_id'],
            account_in_id=tx_data.get('account_in_id'),
            amount_minor=tx_data['amount_minor'],
            note=tx_data.get('note'),
            source=tx_data.get('source', 'import'),
            is_cleared=tx_data.get('is_cleared', False),
            is_locked=tx_data.get('is_locked', False),
        )
        session.add(tx)
        self._add_legacy_map(
            'transactions',
            str(tx_data.get('legacy_id', '')),
            'transactions', new_id,
        )
        self._stats['transactions_imported'] += 1

    def _generate_settlement_transactions(
        self, account_map: dict[int, str]
    ) -> list[dict]:
        if self._stock_strategy != 'historical_snapshot' or self._plan is None:
            return []
        stxs: list[dict] = []
        for abp in self._plan.account_balance_plans:
            if not abp.is_linked_stock or abp.diff_minor == 0:
                continue
            new_acct_id = account_map.get(abp.legacy_id)
            if new_acct_id is None:
                continue
            stxs.append({
                'transaction_date': date(2000, 1, 1),
                'type': str(TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT),
                'category_id': None,
                'account_out_id': new_acct_id,
                'account_in_id': None,
                'amount_minor': abs(abp.diff_minor),
                'note': (
                    f'历史投资估值调节：旧余额 {abp.new_balance_minor} 分'
                    f'与重算 {abp.recomputed_balance_minor} 分'
                    f'差额 {abp.diff_minor:+d} 分'
                ),
                'source': 'import',
                'is_locked': True, 'is_cleared': True,
                'legacy_id': f'settlement_{abp.legacy_id}',
            })
        return stxs

    def _migrate_budget_periods(
        self, session: Session, rows: list[dict]
    ) -> dict[int, str]:
        pmap: dict[int, str] = {}
        for row in rows:
            try:
                lid = int(row['id'])
                new_id = str(uuid.uuid4())
                period = BudgetPeriod(
                    id=new_id,
                    year=int(row.get('year', 2000)),
                    month=int(row.get('month', 1)),
                )
                session.add(period)
                pmap[lid] = new_id
                self._add_legacy_map(
                    'budget_months', str(lid), 'budget_periods', new_id)
                self._stats['budget_periods_imported'] += 1
            except Exception as e:
                self._stats['failed'] += 1
                logger.warning('预算期间 %s 迁移失败: %s', row.get('id'), e)
        session.flush()
        return pmap

    def _migrate_budget_lines(
        self, session: Session, rows: list[dict],
        period_map: dict[int, str], category_map: dict[int, str],
    ) -> None:
        for row in rows:
            try:
                opid = row.get('budget_month_id')
                ocid = row.get('category_id')
                npid = period_map.get(opid)
                ncid = category_map.get(ocid)
                if npid is None or ncid is None:
                    self._stats['skipped'] += 1
                    continue
                amt = convert_amount_to_minor(row.get('amount', 0)).minor
                new_id = str(uuid.uuid4())
                line = BudgetLine(
                    id=new_id, budget_period_id=npid, category_id=ncid,
                    amount_minor=amt,
                    note=str(row.get('note') or ''),
                )
                session.add(line)
                self._add_legacy_map(
                    'budget_lines', str(row['id']), 'budget_lines', new_id)
                self._stats['budget_lines_imported'] += 1
            except Exception as e:
                self._stats['failed'] += 1
                logger.warning('预算行 %s 迁移失败: %s', row.get('id'), e)

    def _migrate_settings(
        self, session: Session, rows: list[dict]
    ) -> None:
        for row in rows:
            key = str(row.get('key') or '')
            value = str(row.get('value') or '')
            if not is_settings_allowed(key):
                self._stats['skipped'] += 1
                continue
            try:
                setting = AppSetting(
                    id=str(uuid.uuid4()), key=key, value=value)
                session.add(setting)
                self._stats['settings_imported'] += 1
            except Exception as e:
                self._stats['failed'] += 1
                logger.warning('Settings %s 迁移失败: %s', key, e)

    def _archive_stock_data(
        self, session: Session, legacy_data: dict[str, list[dict]]
    ) -> None:
        blocked = {'password', 'secret', 'token', 'key'}
        for tbl in legacy_data:
            if not tbl.startswith('stock_'):
                continue
            for row in legacy_data[tbl]:
                try:
                    safe_row = {
                        k: v for k, v in row.items()
                        if not any(s in str(k).lower() for s in blocked)
                    }
                    archive = LegacyArchiveRecord(
                        id=str(uuid.uuid4()),
                        import_run_id=self._import_run_id,
                        source_table=tbl,
                        legacy_id=str(row.get('id', '')),
                        data_json=json.dumps(
                            safe_row, ensure_ascii=False, default=str),
                        summary=f'{tbl} 归档 ({row.get("id", "")})',
                    )
                    session.add(archive)
                    self._stats['archived'] += 1
                except Exception as e:
                    self._stats['failed'] += 1
                    logger.warning(
                        '归档 %s.%s 失败: %s', tbl, row.get('id'), e)

    def _archive_ai_data(
        self, session: Session, legacy_data: dict[str, list[dict]]
    ) -> None:
        for tbl in ('ai_chat_messages', 'ai_imported_records'):
            for row in legacy_data.get(tbl, []):
                try:
                    archive = LegacyArchiveRecord(
                        id=str(uuid.uuid4()),
                        import_run_id=self._import_run_id,
                        source_table=tbl,
                        legacy_id=str(row.get('id', '')),
                        data_json=json.dumps(
                            dict(row), ensure_ascii=False, default=str),
                        summary=f'AI 历史数据归档: {tbl}#{row.get("id", "")}',
                    )
                    session.add(archive)
                    self._stats['archived'] += 1
                except Exception as e:
                    self._stats['failed'] += 1
                    logger.warning(
                        'AI 归档 %s.%s 失败: %s', tbl, row.get('id'), e)

    def _recalculate_all_balances(self, session: Session) -> None:
        accounts = session.scalars(select(Account)).all()
        for account in accounts:
            txs = session.scalars(
                select(Transaction).where(
                    (Transaction.account_out_id == account.id)
                    | (Transaction.account_in_id == account.id)
                )
            ).all()
            balance = account.opening_balance_minor
            is_asset = is_asset_account(account.type)
            for tx in txs:
                if tx.type in (
                    str(TransactionType.BALANCE_ADJUSTMENT),
                    str(TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT),
                ):
                    if tx.account_out_id == account.id:
                        balance += tx.amount_minor
                elif (
                    tx.type == str(TransactionType.INCOME)
                    and tx.account_out_id == tx.account_in_id
                ):
                    if tx.account_in_id == account.id:
                        balance += (
                            tx.amount_minor if is_asset else -tx.amount_minor
                        )
                else:
                    if tx.account_out_id == account.id:
                        balance += (
                            -tx.amount_minor if is_asset else tx.amount_minor
                        )
                    if tx.account_in_id == account.id:
                        balance += (
                            tx.amount_minor if is_asset else -tx.amount_minor
                        )
            account.current_balance_minor = balance
        session.flush()

    def _verify_migration(self) -> dict:
        engine = create_mym2_engine(self._target_db_path)
        try:
            with Session(engine) as session:
                result: dict[str, Any] = {
                    'fk_ok': True, 'fk_violations': 0,
                    'integrity_ok': True,
                    'balance_checks': [], 'tx_type_counts': {},
                    'errors': [], 'warnings': [],
                }
                try:
                    vios = session.execute(
                        text('PRAGMA foreign_key_check')).fetchall()
                    result['fk_violations'] = len(vios)
                    result['fk_ok'] = len(vios) == 0
                except Exception as e:
                    result['errors'].append(f'FK 检查失败: {e}')
                try:
                    integ = session.execute(
                        text('PRAGMA integrity_check')).fetchone()
                    ok = integ and integ[0].lower() == 'ok'
                    result['integrity_ok'] = ok
                except Exception as e:
                    result['errors'].append(f'完整性检查失败: {e}')
                counts = session.execute(
                    select(Transaction.type, func.count())
                    .group_by(Transaction.type)
                ).all()
                result['tx_type_counts'] = {t: c for t, c in counts}
                if self._plan:
                    for abp in self._plan.account_balance_plans:
                        result['balance_checks'].append({
                            'legacy_id': abp.legacy_id,
                            'legacy_name': abp.legacy_name,
                            'is_linked_stock': abp.is_linked_stock,
                        })
                dupes = session.execute(
                    select(
                        LegacyIdMap.source_table,
                        LegacyIdMap.legacy_id,
                        func.count(),
                    )
                    .where(LegacyIdMap.import_run_id == self._import_run_id)
                    .group_by(
                        LegacyIdMap.source_table, LegacyIdMap.legacy_id)
                    .having(func.count() > 1)
                ).all()
                if dupes:
                    result['errors'].append(
                        f'LegacyIdMap 重复: {len(dupes)} 条')
                return result
        finally:
            engine.dispose()

    def _generate_report(
        self, verification: dict, backup_path: Path | None
    ) -> dict:
        return {
            'status': 'completed',
            'source_path': str(self._source_path),
            'source_hash': self._source_hash,
            'target_db': str(self._target_db_path),
            'backup_path': str(backup_path) if backup_path else None,
            'stock_strategy': self._stock_strategy,
            'import_run_id': self._import_run_id,
            'stats': dict(self._stats),
            'verification': verification,
            'plan_summary': self._plan.to_dict() if self._plan else {},
        }

    def _get_linked_ids(self) -> set[int]:
        if self._plan is None:
            return set()
        return {
            abp.legacy_id for abp in self._plan.account_balance_plans
            if abp.is_linked_stock
        }

    def _add_legacy_map(
        self, source_table: str, legacy_id: str,
        new_table: str, new_id: str,
    ) -> None:
        self._legacy_id_maps.append(
            (source_table, legacy_id, new_table, new_id))

    def _write_legacy_id_maps(self, session: Session) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        for st, lid, nt, nid in self._legacy_id_maps:
            entry = LegacyIdMap(
                id=str(uuid.uuid4()),
                import_run_id=self._import_run_id,
                source_table=st, legacy_id=lid,
                new_table=nt, new_id=nid,
                created_at=now,
            )
            session.add(entry)
        self._legacy_id_maps.clear()

    @staticmethod
    def _parse_date(val: str | None) -> date:
        if val is None:
            return date(2000, 1, 1)
        try:
            return date.fromisoformat(str(val)[:10])
        except (ValueError, TypeError):
            return date(2000, 1, 1)
