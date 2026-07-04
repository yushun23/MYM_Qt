"""旧库到新领域模型的映射器。

从 schema_probe 实际检查结果和源码读取规则；
遇到未知表/未知交易类型标记"需确认"，不猜测。
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from dataclasses import dataclass, field

from mym2.importers.legacy_mym.migration_plan import (
    AccountBalancePlan,
    MigrationPlan,
    MigrationRisk,
    PendingConfirmation,
    TablePlan,
)
from mym2.importers.legacy_mym.source_reader import SourceReader
from mym2.importers.legacy_mym.validators import (
    convert_amount_to_minor,
    is_settings_allowed,
    is_settings_blocked,
    map_account_type,
    map_transaction_type,
)

logger = logging.getLogger('mym2.importers.legacy_mym.mapper')

# ── 核心优先表（按迁移顺序）──────────────────────────
_PRIORITY_TABLES: tuple[str, ...] = (
    'accounts',
    'categories',
    'transactions',
    'budget_months',
    'budget_items',
    'budget_lines',
)

# ── 股票归档表（全量归档）───────────────────────────
_STOCK_ARCHIVE_TABLES: frozenset[str] = frozenset({
    'stock_accounts',
    'stock_cash_flows',
    'stock_trades',
    'stock_quotes',
    'stock_symbols',
    'stock_settlement_imports',
    'stock_monthly_settlements',
    'stock_module_meta',
})

# ── 选择性处理表 ────────────────────────────────────
_SELECTIVE_TABLES: frozenset[str] = frozenset({
    'settings',
    'ai_chat_messages',
    'ai_imported_records',
})

# ── 跳过表 ──────────────────────────────────────────
_SKIP_TABLES: frozenset[str] = frozenset({
    'schema_migrations',
    'sqlite_sequence',
})


@dataclass
class MappedRow:
    """一条映射后的新数据行（键值对字典，尚未写入 DB）。"""

    table: str
    data: dict
    legacy_id: str
    legacy_table: str
    note: str = ''


@dataclass
class MappingContext:
    """映射上下文 — 追踪已映射的 ID 映射表。"""

    account_id_map: dict[int, str] = field(default_factory=dict)
    category_id_map: dict[int, str] = field(default_factory=dict)
    budget_period_id_map: dict[int, str] = field(default_factory=dict)
    linked_stock_account_ids: set[int] = field(default_factory=set)
    unknown_transaction_types: dict[str, int] = field(default_factory=dict)
    unknown_account_types: dict[str, int] = field(default_factory=dict)
    amount_issues: list[str] = field(default_factory=list)
    total_mapped: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    pending_confirmations: list[PendingConfirmation] = field(default_factory=list)


class LegacyMapper:
    """旧 .mym → 新 MYM2 领域模型映射器。

    仅生成映射计划，不写入目标业务数据。
    从 SourceReader 读取旧数据，转换为新模型数据字典。
    """

    def __init__(
        self,
        reader: SourceReader,
        stock_strategy: str = 'historical_snapshot',
    ) -> None:
        self._r = reader
        self._stock_strategy = stock_strategy
        self._ctx = MappingContext()

    # ── 主入口 ────────────────────────────────────────

    def build_plan(self) -> MigrationPlan:
        """构建完整迁移计划。"""
        plan = MigrationPlan()
        self._ctx = MappingContext()

        all_tables = self._r.get_tables()
        known_tables = set(all_tables)

        self._ctx.linked_stock_account_ids = self._detect_linked_stock_ids()

        # 优先表
        for tbl in _PRIORITY_TABLES:
            if tbl in known_tables:
                plan.table_plans.append(self._plan_table(tbl))

        # 选择性表
        for tbl in sorted(_SELECTIVE_TABLES & known_tables):
            plan.table_plans.append(self._plan_table(tbl))

        # 股票归档表
        for tbl in sorted(_STOCK_ARCHIVE_TABLES & known_tables):
            plan.table_plans.append(self._plan_stock_archive(tbl))

        # 跳过表
        for tbl in sorted(_SKIP_TABLES & known_tables):
            row_count = self._r.get_row_count(tbl)
            plan.table_plans.append(TablePlan(
                table_name=tbl,
                total_rows=row_count,
                rows_to_skip=row_count,
                note='系统表/旧迁移记录，跳过',
            ))

        # 未知表
        all_handled = (
            set(_PRIORITY_TABLES)
            | _SELECTIVE_TABLES
            | _STOCK_ARCHIVE_TABLES
            | _SKIP_TABLES
        )
        for tbl in sorted(known_tables - all_handled):
            row_count = self._r.get_row_count(tbl)
            plan.table_plans.append(TablePlan(
                table_name=tbl,
                total_rows=row_count,
                rows_to_skip=row_count,
                note='未知表，需确认',
            ))
            plan.pending_confirmations.append(PendingConfirmation(
                category='未知表',
                item=f'表 {tbl}（{row_count} 行）',
                reason=f'表 {tbl} 不在已知分类中',
                suggestion='请确认是否需要迁移或归档此表',
            ))

        plan.account_balance_plans = self._build_balance_plans()
        plan.estimated_new_records = self._ctx.total_mapped
        plan.pending_confirmations = self._ctx.pending_confirmations
        plan.risks = self._build_risks(plan)
        plan.warnings = list(dict.fromkeys(self._ctx.amount_issues))

        return plan

    # ── 按表规划 ──────────────────────────────────────

    def _plan_table(self, table_name: str) -> TablePlan:
        """对一张核心/选择性表生成映射计划。"""
        row_count = self._r.get_row_count(table_name)
        tp = TablePlan(table_name=table_name, total_rows=row_count)

        if table_name == 'accounts':
            tp = self._map_accounts(tp)
        elif table_name == 'categories':
            tp = self._map_categories(tp)
        elif table_name == 'transactions':
            tp = self._map_transactions(tp)
        elif table_name == 'budget_months':
            tp = self._map_budget_months(tp)
        elif table_name == 'budget_items':
            tp = self._map_budget_items(tp)
        elif table_name == 'budget_lines':
            tp = self._map_budget_lines(tp)
        elif table_name == 'settings':
            tp = self._map_settings(tp)
        elif table_name in ('ai_chat_messages', 'ai_imported_records'):
            tp.rows_to_archive = row_count
            tp.note = 'AI 历史数据写入通用归档，不进入新 AI 上下文'
            self._ctx.total_mapped += row_count
        else:
            tp.rows_to_skip = row_count
            tp.note = '未实现映射的表'

        return tp

    def _plan_stock_archive(self, table_name: str) -> TablePlan:
        """对股票表生成归档计划。"""
        row_count = self._r.get_row_count(table_name)
        tp = TablePlan(table_name=table_name, total_rows=row_count)

        if self._stock_strategy == 'skip':
            tp.rows_to_skip = row_count
            tp.note = 'stock_strategy=skip，跳过'
        elif self._stock_strategy == 'archive_only':
            tp.rows_to_archive = row_count
            tp.note = '股票数据全部归档到 legacy_archive_records'
            self._ctx.total_mapped += row_count
        else:  # historical_snapshot
            tp.rows_to_archive = row_count
            tp.note = (
                '股票数据归档；'
                f'{len(self._ctx.linked_stock_account_ids)} 个链接证券账户'
                '按 historical_snapshot 处理'
            )
            self._ctx.total_mapped += row_count

        return tp

    # ── 账户映射 ──────────────────────────────────────

    def _map_accounts(self, tp: TablePlan) -> TablePlan:
        """映射旧 accounts 表。"""
        try:
            rows = self._r.fetch_all(
                'SELECT id, name, type, balance, is_active, group_name, '
                'linked_stock_account_id, is_system_locked, opening_balance '
                'FROM accounts ORDER BY id'
            )
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        for row in rows:
            try:
                self._map_single_account(dict(row))
                tp.rows_to_migrate += 1
                self._ctx.total_mapped += 1
            except Exception as e:
                tp.rows_failed += 1
                logger.warning('账户 %s 映射失败: %s', row['id'], e)

        tp.rows_confirmed = len(self._ctx.linked_stock_account_ids)
        return tp

    def _map_single_account(self, row: dict) -> None:
        """映射单个账户行。"""
        legacy_id = int(row['id'])
        name = str(row.get('name') or '')
        old_type = str(row.get('type') or 'Asset')

        is_linked = legacy_id in self._ctx.linked_stock_account_ids
        bool(row.get('is_system_locked', 0))

        if is_linked and self._stock_strategy == 'historical_snapshot':
            new_type = 'investment_snapshot'
        elif is_linked and self._stock_strategy == 'archive_only':
            new_type_map = map_account_type(old_type)
            new_type = new_type_map if new_type_map else 'cash'
        elif is_linked and self._stock_strategy == 'skip':
            self._ctx.total_skipped += 1
            return
        else:
            new_type_map = map_account_type(old_type)
            if new_type_map is None:
                new_type = 'cash'
                self._ctx.unknown_account_types[old_type] = (
                    self._ctx.unknown_account_types.get(old_type, 0) + 1
                )
                self._ctx.pending_confirmations.append(PendingConfirmation(
                    category='未知账户类型',
                    item=f'{name} (ID={legacy_id}, type={old_type})',
                    reason=f'旧账户类型 "{old_type}" 无对应新类型映射',
                    suggestion='将默认映射为 cash，请确认',
                ))
            else:
                new_type = new_type_map

        balance_result = convert_amount_to_minor(row.get('balance'))
        opening_result = convert_amount_to_minor(row.get('opening_balance', 0))
        if not balance_result.is_acceptable:
            self._ctx.amount_issues.append(balance_result.note)
        if not opening_result.is_acceptable:
            self._ctx.amount_issues.append(opening_result.note)

        new_uuid = str(uuid.uuid4())
        self._ctx.account_id_map[legacy_id] = new_uuid

        logger.debug(
            '映射账户: %s (ID=%d → %s, type=%s → %s, balance=%d)',
            name, legacy_id, new_uuid, old_type, new_type, balance_result.minor,
        )

    # ── 分类映射 ──────────────────────────────────────

    def _map_categories(self, tp: TablePlan) -> TablePlan:
        """映射旧 categories 表。"""
        try:
            rows = self._r.fetch_all(
                'SELECT id, name, type, is_active, group_name FROM categories ORDER BY id'
            )
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        for row in rows:
            try:
                d = dict(row)
                legacy_id = int(d['id'])
                new_uuid = str(uuid.uuid4())
                self._ctx.category_id_map[legacy_id] = new_uuid
                tp.rows_to_migrate += 1
                self._ctx.total_mapped += 1
            except Exception as e:
                tp.rows_failed += 1
                logger.warning('分类 %s 映射失败: %s', row['id'], e)

        return tp

    # ── 流水映射 ──────────────────────────────────────

    def _map_transactions(self, tp: TablePlan) -> TablePlan:
        """映射旧 transactions 表。"""
        try:
            rows = self._r.fetch_all(
                'SELECT id, trans_date, trans_type, category_id, '
                'account_out_id, account_in_id, amount, note, is_cleared '
                'FROM transactions ORDER BY id'
            )
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        for row in rows:
            try:
                self._map_single_transaction(dict(row))
                tp.rows_to_migrate += 1
                self._ctx.total_mapped += 1
            except Exception as e:
                tp.rows_failed += 1
                logger.warning('流水 %s 映射失败: %s', row['id'], e)

        for utype, cnt in self._ctx.unknown_transaction_types.items():
            self._ctx.pending_confirmations.append(PendingConfirmation(
                category='未知交易类型',
                item=f'{utype}（{cnt} 笔）',
                reason=f'旧交易类型 "{utype}" 无对应新类型映射',
                suggestion='请手工确认这些交易应映射为何种新类型',
            ))

        tp.rows_confirmed = sum(self._ctx.unknown_transaction_types.values())
        return tp

    def _map_single_transaction(self, row: dict) -> None:
        """映射单条流水。"""
        legacy_id = int(row['id'])
        old_type = str(row.get('trans_type') or '')

        new_type = map_transaction_type(old_type)
        if new_type is None:
            new_type = 'expense'
            self._ctx.unknown_transaction_types[old_type] = (
                self._ctx.unknown_transaction_types.get(old_type, 0) + 1
            )

        amount_result = convert_amount_to_minor(row.get('amount'))
        if not amount_result.is_acceptable:
            self._ctx.amount_issues.append(
                f'流水 {legacy_id}: {amount_result.note}'
            )

        logger.debug(
            '映射流水: ID=%d, type=%s→%s, amount=%d',
            legacy_id, old_type, new_type, amount_result.minor,
        )

    # ── 预算映射 ──────────────────────────────────────

    def _map_budget_months(self, tp: TablePlan) -> TablePlan:
        """映射旧 budget_months → 新 budget_periods。"""
        try:
            rows = self._r.fetch_all(
                'SELECT id, year, month FROM budget_months ORDER BY id'
            )
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        for row in rows:
            try:
                d = dict(row)
                legacy_id = int(d['id'])
                new_uuid = str(uuid.uuid4())
                self._ctx.budget_period_id_map[legacy_id] = new_uuid
                tp.rows_to_migrate += 1
                self._ctx.total_mapped += 1
            except Exception as e:
                tp.rows_failed += 1
                logger.warning('预算月份 %s 映射失败: %s', row['id'], e)

        return tp

    def _map_budget_items(self, tp: TablePlan) -> TablePlan:
        """映射旧 budget_items → 预算项目定义。

        旧 budget_items 表定义预算项目（名称、金额等），
        在新系统中可能映射为预算行的一部分或预算模板。
        当前将整行数据归档，等待用户确认映射方式。
        """
        try:
            rows = self._r.fetch_all('SELECT * FROM budget_items ORDER BY id')
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        tp.rows_to_migrate = len(rows)
        tp.note = '预算项目定义，按旧结构迁移；金额已转分'
        self._ctx.total_mapped += len(rows)

        for row in rows:
            d = dict(row)
            for key, val in d.items():
                if val is not None and isinstance(val, float):
                    result = convert_amount_to_minor(val)
                    if not result.is_acceptable:
                        self._ctx.amount_issues.append(
                            f'budget_items {d["id"]}.{key}: {result.note}'
                        )

        return tp

    def _map_budget_lines(self, tp: TablePlan) -> TablePlan:
        """映射旧 budget_lines → 新 BudgetLine。"""
        try:
            rows = self._r.fetch_all(
                'SELECT id, budget_month_id, category_id, amount, note '
                'FROM budget_lines ORDER BY id'
            )
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        for row in rows:
            try:
                d = dict(row)
                amount_result = convert_amount_to_minor(d.get('amount'))
                if not amount_result.is_acceptable:
                    self._ctx.amount_issues.append(
                        f'budget_lines {d["id"]}: {amount_result.note}'
                    )
                tp.rows_to_migrate += 1
                self._ctx.total_mapped += 1
            except Exception as e:
                tp.rows_failed += 1
                logger.warning('预算行 %s 映射失败: %s', row['id'], e)

        return tp

    # ── Settings 映射 ─────────────────────────────────

    def _map_settings(self, tp: TablePlan) -> TablePlan:
        """映射旧 settings 表（白名单过滤）。"""
        try:
            rows = self._r.fetch_all('SELECT key, value FROM settings')
        except Exception as e:
            tp.rows_failed = tp.total_rows
            tp.note = f'读取失败: {e}'
            return tp

        allowed_count = 0
        skipped_count = 0

        for row in rows:
            d = dict(row)
            key = str(d.get('key') or '')
            if is_settings_allowed(key):
                allowed_count += 1
                self._ctx.total_mapped += 1
            elif is_settings_blocked(key):
                skipped_count += 1
            else:
                skipped_count += 1
                self._ctx.pending_confirmations.append(PendingConfirmation(
                    category='settings 未分类',
                    item=f'键 "{key}"',
                    reason=f'settings 键 "{key}" 不在白名单也不在黑名单',
                    suggestion='如需迁移，请确认后手动添加',
                ))

        tp.rows_to_migrate = allowed_count
        tp.rows_to_skip = skipped_count
        tp.note = f'白名单 {allowed_count} 条，跳过 {skipped_count} 条（含敏感键）'
        return tp

    # ── 余额计划 ──────────────────────────────────────

    def _build_balance_plans(self) -> list[AccountBalancePlan]:
        """构建账户余额迁移计划。"""
        plans: list[AccountBalancePlan] = []

        try:
            rows = self._r.fetch_all(
                'SELECT id, name, type, balance, opening_balance '
                'FROM accounts ORDER BY id'
            )
        except Exception:
            return plans

        for row in rows:
            d = dict(row)
            acct_id = int(d['id'])
            name = str(d.get('name') or '')
            old_type = str(d.get('type') or 'Asset')
            balance_real = float(d.get('balance') or 0.0)
            is_linked = acct_id in self._ctx.linked_stock_account_ids

            balance_minor = convert_amount_to_minor(balance_real).minor
            recomputed_minor = self._compute_recomputed_balance_minor(acct_id, old_type)

            diff = balance_minor - recomputed_minor

            plan = AccountBalancePlan(
                legacy_id=acct_id,
                legacy_name=name,
                legacy_type=old_type,
                legacy_balance_real=balance_real,
                new_balance_minor=balance_minor,
                recomputed_balance_minor=recomputed_minor,
                diff_minor=diff,
                is_linked_stock=is_linked,
                strategy=self._stock_strategy if is_linked else 'direct',
                note='',
            )

            if is_linked and self._stock_strategy == 'historical_snapshot':
                if abs(diff) > 100:
                    plan.note = (
                        f'链接证券账户，余额差异 {diff:+d} 分。'
                        f'将创建不可编辑历史投资资产快照账户'
                        f'（balance={balance_minor} 分），'
                        f'并生成 historical_investment_settlement 调节流水'
                        f'（{diff:+d} 分）补齐差额。'
                    )
                else:
                    plan.note = (
                        f'链接证券账户，创建不可编辑历史投资资产快照。'
                        f'重算差异 {diff:+d} 分，在容忍范围内。'
                    )
            elif is_linked and self._stock_strategy == 'archive_only':
                plan.note = '链接证券账户仅归档原始数据，不创建快照账户'
            elif is_linked and self._stock_strategy == 'skip':
                plan.note = '链接证券账户跳过'
            elif abs(diff) > 100:
                plan.note = f'余额差异 {diff:+d} 分，可能需手动调节'
            elif abs(diff) > 1:
                plan.note = f'轻微差异 {diff:+d} 分，REAL→INTEGER 转换造成'

            plans.append(plan)

        return plans

    # ── 风险分析 ──────────────────────────────────────

    def _build_risks(self, plan: MigrationPlan) -> list[MigrationRisk]:
        """构建迁移风险列表。"""
        risks: list[MigrationRisk] = []

        if self._ctx.amount_issues:
            risks.append(MigrationRisk(
                severity='medium',
                description=(
                    f'{len(self._ctx.amount_issues)} 条记录存在金额转换精度差异'
                    '（REAL→INTEGER 分）'
                ),
                affected_table=', '.join(
                    sorted({tp.table_name for tp in plan.table_plans})
                ),
                mitigation='差异在 ±1 分内的记录自动舍入；超过 1 分的需人工检查',
            ))

        if self._ctx.unknown_transaction_types:
            types_str = ', '.join(self._ctx.unknown_transaction_types)
            risks.append(MigrationRisk(
                severity='high',
                description=f'存在未知交易类型: {types_str}',
                affected_table='transactions',
                mitigation='需要用户确认映射方式；未确认的映射为 expense',
            ))

        large_diffs = [
            a for a in plan.account_balance_plans
            if abs(a.diff_minor) > 100 and not a.is_linked_stock
        ]
        if large_diffs:
            risks.append(MigrationRisk(
                severity='high',
                description=(
                    f'{len(large_diffs)} 个非链接证券账户存在大额余额差异'
                    f'（>100 分）'
                ),
                affected_table='accounts',
                mitigation='建议在正式迁移前通过余额调节流水补齐差额',
            ))

        unknown = [
            tp for tp in plan.table_plans
            if tp.note == '未知表，需确认'
        ]
        if unknown:
            risks.append(MigrationRisk(
                severity='medium',
                description=f'存在未知表: {", ".join(tp.table_name for tp in unknown)}',
                affected_table=', '.join(tp.table_name for tp in unknown),
                mitigation='需确认这些表是否需要迁移或归档',
            ))

        if self._stock_strategy == 'historical_snapshot':
            stock_diffs = [
                a for a in plan.account_balance_plans
                if a.is_linked_stock and abs(a.diff_minor) > 100
            ]
            if stock_diffs:
                risks.append(MigrationRisk(
                    severity='medium',
                    description=(
                        f'{len(stock_diffs)} 个链接证券账户存在较大余额差异，'
                        f'将生成历史估值调节流水'
                    ),
                    affected_table='accounts, transactions',
                    mitigation=(
                        '已计划生成 historical_investment_settlement 流水补齐差额；'
                        '该流水不纳入日常收支/预算统计'
                    ),
                ))

        return risks

    # ── 内部辅助 ──────────────────────────────────────

    def _detect_linked_stock_ids(self) -> set[int]:
        """识别链接证券账户 ID 集合。"""
        linked: set[int] = set()

        try:
            rows = self._r.fetch_all(
                'SELECT id FROM accounts WHERE linked_stock_account_id IS NOT NULL'
            )
            linked.update(int(r['id']) for r in rows)
        except Exception:
            pass

        try:
            rows = self._r.fetch_all(
                'SELECT id FROM accounts WHERE is_system_locked = 1'
            )
            linked.update(int(r['id']) for r in rows)
        except Exception:
            pass

        try:
            rows = self._r.fetch_all(
                "SELECT id FROM accounts WHERE group_name LIKE '%证券%' "
                "OR group_name LIKE '%股票%' OR group_name LIKE '%上市%'"
            )
            linked.update(int(r['id']) for r in rows)
        except Exception:
            pass

        try:
            stock_accts = self._r.fetch_all('SELECT id FROM stock_accounts')
            if stock_accts:
                rows = self._r.fetch_all(
                    "SELECT id, name, group_name FROM accounts "
                    "WHERE name LIKE '%证券%' OR name LIKE '%股票%' "
                    "OR group_name LIKE '%证券%' OR group_name LIKE '%股票%'"
                )
                linked.update(int(r['id']) for r in rows)
        except Exception:
            pass

        logger.info('检测到 %d 个链接证券账户: %s', len(linked), sorted(linked))
        return linked

    def _compute_recomputed_balance_minor(
        self, account_id: int, account_type: str
    ) -> int:
        """从旧流水计算账户余额（返回 INTEGER 分）。"""
        opening_minor = 0
        try:
            row = self._r.fetch_one(
                'SELECT COALESCE(opening_balance, 0) AS ob FROM accounts WHERE id = ?',
                (account_id,),
            )
            if row:
                opening_minor = convert_amount_to_minor(row['ob']).minor
        except Exception:
            pass

        out_real = 0.0
        with contextlib.suppress(Exception):
            out_real = self._r.fetch_scalar(
                'SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_out_id = ?',
                (account_id,),
            ) or 0.0

        in_real = 0.0
        with contextlib.suppress(Exception):
            in_real = self._r.fetch_scalar(
                'SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_in_id = ?',
                (account_id,),
            ) or 0.0

        out_minor = convert_amount_to_minor(out_real).minor
        in_minor = convert_amount_to_minor(in_real).minor

        is_liability = account_type.lower() in ('liability', 'credit_card', 'credit')

        if is_liability:
            return opening_minor + out_minor - in_minor
        else:
            return opening_minor - out_minor + in_minor
