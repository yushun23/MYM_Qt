"""迁移计划数据结构。

定义 MigrationPlan 及辅助数据类，支持 JSON 序列化/反序列化。
dry-run 两次连续执行在稳定排序下 JSON 输出必须一致（幂等）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

_MIGRATION_PLAN_VERSION = '1.0.0'


@dataclass
class TablePlan:
    """单张表的迁移计划统计。"""

    table_name: str
    total_rows: int
    rows_to_migrate: int = 0
    rows_to_archive: int = 0
    rows_to_skip: int = 0
    rows_failed: int = 0
    rows_confirmed: int = 0
    note: str = ''


@dataclass
class AccountBalancePlan:
    """单个账户的余额迁移信息。"""

    legacy_id: int
    legacy_name: str
    legacy_type: str
    legacy_balance_real: float
    new_balance_minor: int
    recomputed_balance_minor: int
    diff_minor: int
    is_linked_stock: bool = False
    strategy: str = ''
    note: str = ''


@dataclass
class PendingConfirmation:
    """需要用户确认的迁移项。"""

    category: str
    item: str
    reason: str
    suggestion: str = ''


@dataclass
class MigrationRisk:
    """迁移风险项。"""

    severity: str
    description: str
    affected_table: str = ''
    mitigation: str = ''


@dataclass
class MigrationPlan:
    """完整的迁移计划。

    支持 JSON 序列化；两次连续 dry-run 在稳定排序下应一致。
    """

    plan_version: str = _MIGRATION_PLAN_VERSION
    generated_at: str = ''
    source_path: str = ''
    source_hash: str = ''
    stock_strategy: str = 'historical_snapshot'
    estimated_new_records: int = 0

    table_plans: list[TablePlan] = field(default_factory=list)
    account_balance_plans: list[AccountBalancePlan] = field(default_factory=list)
    pending_confirmations: list[PendingConfirmation] = field(default_factory=list)
    risks: list[MigrationRisk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为字典（稳定排序）。"""
        return {
            'plan_version': self.plan_version,
            'generated_at': self.generated_at,
            'source_path': self.source_path,
            'source_hash': self.source_hash,
            'stock_strategy': self.stock_strategy,
            'estimated_new_records': self.estimated_new_records,
            'table_plans': sorted(
                [asdict(t) for t in self.table_plans],
                key=lambda x: x['table_name'],
            ),
            'account_balance_plans': sorted(
                [asdict(a) for a in self.account_balance_plans],
                key=lambda x: x['legacy_id'],
            ),
            'pending_confirmations': sorted(
                [asdict(p) for p in self.pending_confirmations],
                key=lambda x: (x['category'], x['item']),
            ),
            'risks': sorted(
                [asdict(r) for r in self.risks],
                key=lambda x: (x['severity'], x['description']),
            ),
            'warnings': sorted(self.warnings),
        }

    def to_json(self, *, indent: int = 2) -> str:
        """序列化为 JSON 字符串（稳定排序）。"""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            default=str,
        )

    @classmethod
    def from_dict(cls, data: dict) -> MigrationPlan:
        """从字典反序列化。"""
        return cls(
            plan_version=data.get('plan_version', _MIGRATION_PLAN_VERSION),
            generated_at=data.get('generated_at', ''),
            source_path=data.get('source_path', ''),
            source_hash=data.get('source_hash', ''),
            stock_strategy=data.get('stock_strategy', 'historical_snapshot'),
            estimated_new_records=data.get('estimated_new_records', 0),
            table_plans=[
                TablePlan(**t) for t in data.get('table_plans', [])
            ],
            account_balance_plans=[
                AccountBalancePlan(**a)
                for a in data.get('account_balance_plans', [])
            ],
            pending_confirmations=[
                PendingConfirmation(**p)
                for p in data.get('pending_confirmations', [])
            ],
            risks=[MigrationRisk(**r) for r in data.get('risks', [])],
            warnings=data.get('warnings', []),
        )

    @classmethod
    def from_json(cls, text: str) -> MigrationPlan:
        """从 JSON 字符串反序列化。"""
        return cls.from_dict(json.loads(text))

    @staticmethod
    def utc_now_iso() -> str:
        """当前 UTC 时间 ISO 字符串。"""
        return datetime.now(UTC).replace(tzinfo=None).isoformat()
