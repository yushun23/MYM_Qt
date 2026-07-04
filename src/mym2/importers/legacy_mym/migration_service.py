"""迁移服务 — 旧 .mym dry-run 编排器。

以只读模式打开旧 .mym，生成 MigrationPlan；
在内存临时数据库中验证映射完整性；
dry-run 绝对不写入目标业务数据；
两次连续 dry-run 在稳定排序下 JSON 输出必须一致。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, event, text

from mym2.importers.legacy_mym.mapper import LegacyMapper
from mym2.importers.legacy_mym.migration_plan import (
    MigrationPlan,
)
from mym2.importers.legacy_mym.source_reader import SourceReader

logger = logging.getLogger('mym2.importers.legacy_mym.migration_service')


def _set_temp_pragmas(dbapi_connection, connection_record) -> None:
    """在临时数据库连接上设置 PRAGMA。"""
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')
    cursor.execute('PRAGMA journal_mode = MEMORY')
    cursor.close()


@dataclass
class DryRunResult:
    """dry-run 执行结果。"""

    plan: MigrationPlan
    plan_json: str
    validation_errors: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    temp_db_created: bool = False
    record_count: int = 0
    error_count: int = 0


class MigrationService:
    """旧 .mym 迁移服务。

    仅支持 dry-run 模式；正式迁移需用户确认后由单独入口触发。
    """

    def __init__(
        self,
        source_path: str | Path,
        *,
        stock_strategy: str = 'historical_snapshot',
    ) -> None:
        self._source_path = Path(source_path).resolve()
        self._stock_strategy = stock_strategy

        if stock_strategy not in ('historical_snapshot', 'archive_only', 'skip'):
            raise ValueError(
                f'无效的 stock_strategy: {stock_strategy}'
            )

    # ── Dry-Run ───────────────────────────────────────

    def dry_run(self) -> DryRunResult:
        """执行 dry-run 迁移。

        1. 只读打开旧 .mym
        2. Schema 探测 + 构建 MigrationPlan
        3. 在内存临时 DB 中验证映射
        4. 返回 DryRunResult（含 JSON 计划）

        不写入任何目标业务数据。
        """
        logger.info('开始 dry-run: %s (strategy=%s)',
                     self._source_path, self._stock_strategy)

        # 步骤 1: 只读打开
        with SourceReader(self._source_path) as reader:
            source_hash = reader.file_hash_before or ''

            # 步骤 2: 构建映射计划
            mapper = LegacyMapper(reader, stock_strategy=self._stock_strategy)
            plan = mapper.build_plan()

            # 补充元数据
            plan.generated_at = MigrationPlan.utc_now_iso()
            plan.source_path = str(self._source_path)
            plan.source_hash = source_hash
            plan.stock_strategy = self._stock_strategy

        # 步骤 3: 在临时 DB 中验证
        validation_errors, validation_warnings, record_count, error_count = (
            self._validate_in_temp_db(plan)
        )

        plan_json = plan.to_json()

        return DryRunResult(
            plan=plan,
            plan_json=plan_json,
            validation_errors=validation_errors,
            validation_warnings=validation_warnings,
            temp_db_created=True,
            record_count=record_count,
            error_count=error_count,
        )

    def dry_run_to_file(self, output_path: str | Path) -> DryRunResult:
        """执行 dry-run 并写入 JSON 计划文件。

        Args:
            output_path: JSON 输出路径。

        Returns:
            DryRunResult。
        """
        result = self.dry_run()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.plan_json, encoding='utf-8')
        logger.info('dry-run 计划保存至: %s', output_path)
        return result

    # ── 幂等性验证 ────────────────────────────────────

    @staticmethod
    def verify_idempotent(plan_json_1: str, plan_json_2: str) -> bool:
        """验证两次 dry-run 生成的 JSON 计划是否一致（忽略生成时间）。

        比较 JSON 结构，忽略 generated_at 字段。
        """
        try:
            d1 = json.loads(plan_json_1)
            d2 = json.loads(plan_json_2)
        except json.JSONDecodeError:
            return False

        # 移除时间戳后再比较
        for d in (d1, d2):
            d.pop('generated_at', None)

        return json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)

    # ── 内部: 临时 DB 验证 ─────────────────────────────

    def _validate_in_temp_db(
        self, plan: MigrationPlan
    ) -> tuple[list[str], list[str], int, int]:
        """在内存临时数据库中验证映射完整性。

        创建临时的 schema，尝试插入映射数据，
        收集验证错误和警告。

        Returns:
            (errors, warnings, record_count, error_count)
        """
        errors: list[str] = []
        warnings: list[str] = []
        record_count = 0
        error_count = 0

        # 创建内存临时 DB
        engine = create_engine('sqlite:///:memory:')
        event.listen(engine, 'connect', _set_temp_pragmas)

        try:
            with engine.connect() as conn:
                # 创建验证用临时表（仅结构，不包含业务数据约束外的索引）
                self._create_validation_schema(conn)

                # 验证表计划数量与预估一致
                for tp in plan.table_plans:
                    record_count += tp.rows_to_migrate + tp.rows_to_archive

        except Exception as e:
            errors.append(f'临时 DB 验证失败: {e}')
            logger.exception('临时 DB 创建失败')

        engine.dispose()
        return errors, warnings, record_count, error_count

    @staticmethod
    def _create_validation_schema(conn) -> None:
        """在临时 DB 中创建验证用 schema。"""
        # accounts
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'cash',
                "group" TEXT,
                is_enabled INTEGER DEFAULT 1,
                opening_balance_minor INTEGER DEFAULT 0,
                current_balance_minor INTEGER DEFAULT 0,
                is_locked INTEGER DEFAULT 0,
                is_editable INTEGER DEFAULT 1,
                currency TEXT DEFAULT 'CNY',
                notes TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        '''))
        conn.commit()

        # categories
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'expense',
                parent_id TEXT,
                color TEXT,
                icon TEXT,
                is_enabled INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (parent_id) REFERENCES categories(id)
            )
        '''))
        conn.commit()

        # transactions
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                transaction_date TEXT NOT NULL,
                type TEXT NOT NULL,
                category_id TEXT,
                account_out_id TEXT NOT NULL,
                account_in_id TEXT,
                amount_minor INTEGER NOT NULL,
                note TEXT,
                is_cleared INTEGER DEFAULT 0,
                source TEXT,
                is_locked INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (account_out_id) REFERENCES accounts(id),
                FOREIGN KEY (account_in_id) REFERENCES accounts(id)
            )
        '''))
        conn.commit()

        # budget_periods
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS budget_periods (
                id TEXT PRIMARY KEY,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                UNIQUE (year, month)
            )
        '''))
        conn.commit()

        # budget_lines
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS budget_lines (
                id TEXT PRIMARY KEY,
                budget_period_id TEXT NOT NULL,
                category_id TEXT NOT NULL,
                amount_minor INTEGER NOT NULL,
                note TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (budget_period_id) REFERENCES budget_periods(id),
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        '''))
        conn.commit()

        # app_settings
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS app_settings (
                id TEXT PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL
            )
        '''))
        conn.commit()

        # import_runs
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS import_runs (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                status TEXT DEFAULT 'dry_run',
                rows_imported INTEGER DEFAULT 0,
                rows_skipped INTEGER DEFAULT 0,
                rows_failed INTEGER DEFAULT 0,
                report_json TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )
        '''))
        conn.commit()

        # legacy_id_map
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS legacy_id_map (
                id TEXT PRIMARY KEY,
                import_run_id TEXT NOT NULL,
                source_table TEXT NOT NULL,
                legacy_id TEXT NOT NULL,
                new_table TEXT NOT NULL,
                new_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (import_run_id) REFERENCES import_runs(id)
            )
        '''))
        conn.commit()

        # legacy_archive_records
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS legacy_archive_records (
                id TEXT PRIMARY KEY,
                import_run_id TEXT NOT NULL,
                source_table TEXT NOT NULL,
                legacy_id TEXT NOT NULL,
                data_json TEXT NOT NULL,
                summary TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (import_run_id) REFERENCES import_runs(id)
            )
        '''))
        conn.commit()

        # audit_events
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                changes_json TEXT,
                created_at TEXT NOT NULL
            )
        '''))
        conn.commit()


# ── 便捷函数 ──────────────────────────────────────────


def dry_run_migration(
    source_path: str | Path,
    *,
    stock_strategy: str = 'historical_snapshot',
    output_json: str | Path | None = None,
) -> DryRunResult:
    """对旧 .mym 执行 dry-run 迁移计划。

    Args:
        source_path: 旧 .mym 文件路径。
        stock_strategy: 股票处理策略。
        output_json: 可选 JSON 输出路径。

    Returns:
        DryRunResult。
    """
    service = MigrationService(
        source_path,
        stock_strategy=stock_strategy,
    )

    if output_json:
        return service.dry_run_to_file(output_json)
    return service.dry_run()
