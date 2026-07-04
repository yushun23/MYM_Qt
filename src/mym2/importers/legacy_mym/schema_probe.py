"""旧 .mym Schema 探测器。

在只读 SourceReader 之上执行深度分析：
- 表清单与列详情
- 行数统计
- REAL 类型列检测（金额精度风险）
- 交易类型分布统计
- 链接证券账户识别
- 账户余额按普通流水重算差异
- settings 敏感键检测（不展示值）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mym2.importers.legacy_mym.source_reader import SourceReader

logger = logging.getLogger('mym2.importers.legacy_mym.schema_probe')

# 敏感 settings 键模式（大小写不敏感子串匹配）
_SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    'password', 'secret', 'token', 'key', 'api', 'hash',
    'proxy_username', 'proxy_url', 'auth',
)


@dataclass
class TableInfo:
    """表级别信息。"""

    name: str
    row_count: int
    columns: list[dict] = field(default_factory=list)
    real_columns: list[str] = field(default_factory=list)


@dataclass
class RealAnomaly:
    """REAL 金额类型异常记录。"""

    table: str
    column: str
    description: str


@dataclass
class BalanceDiff:
    """账户余额差异记录。"""

    account_id: int
    account_name: str
    stored_balance_real: float
    computed_balance_real: float
    diff_real: float
    diff_minor: int
    note: str = ''


@dataclass
class LinkedStockInfo:
    """链接证券账户信息。"""

    account_id: int
    account_name: str
    balance_real: float
    linked_stock_account_id: int | None
    is_system_locked: bool


@dataclass
class ProbeResult:
    """Schema 探测完整结果。"""

    tables: dict[str, TableInfo] = field(default_factory=dict)
    real_anomalies: list[RealAnomaly] = field(default_factory=list)
    transaction_type_counts: dict[str, int] = field(default_factory=dict)
    linked_stock_accounts: list[LinkedStockInfo] = field(default_factory=list)
    balance_diffs: list[BalanceDiff] = field(default_factory=list)
    settings_key_count: int = 0
    settings_sensitive_keys: list[str] = field(default_factory=list)
    integrity_errors: list[str] = field(default_factory=list)
    foreign_key_violations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SchemaProbe:
    """旧 .mym 数据库深度探测器。"""

    def __init__(self, reader: SourceReader) -> None:
        self._r = reader
        self._result = ProbeResult()

    # ── 公开方法 ──────────────────────────────────────

    def probe(self) -> ProbeResult:
        """执行完整探测并返回结果。"""
        logger.info('开始 schema 探测...')

        self._probe_integrity()
        self._probe_tables()
        self._probe_real_columns()
        self._probe_transaction_types()
        self._probe_linked_stock()
        self._probe_balance_diffs()
        self._probe_settings()

        logger.info('schema 探测完成: %d 表, %d 异常, %d 差异',
                    len(self._result.tables),
                    len(self._result.real_anomalies),
                    len(self._result.balance_diffs))
        return self._result

    # ── 各步骤 ────────────────────────────────────────

    def _probe_integrity(self) -> None:
        """运行完整性检查。"""
        self._result.integrity_errors = self._r.check_integrity()
        self._result.foreign_key_violations = self._r.check_foreign_keys()

    def _probe_tables(self) -> None:
        """探测所有表的结构和行数。"""
        table_names = self._r.get_tables()

        for name in table_names:
            columns = self._r.get_table_info(name)
            row_count = self._r.get_row_count(name)

            real_cols = [
                col['name'] for col in columns
                if 'REAL' in str(col.get('type', '')).upper()
                or 'FLOAT' in str(col.get('type', '')).upper()
                or 'DOUBLE' in str(col.get('type', '')).upper()
            ]

            info = TableInfo(
                name=name,
                row_count=row_count,
                columns=columns,
                real_columns=real_cols,
            )
            self._result.tables[name] = info

        # 检查核心表是否存在
        for required in ('accounts', 'transactions', 'categories'):
            if required not in self._result.tables:
                self._result.warnings.append(f'缺少核心表: {required}')

    def _probe_real_columns(self) -> None:
        """检测所有 REAL 类型的金额列。"""
        for name, info in self._result.tables.items():
            for col_name in info.real_columns:
                # 只对金额相关列产生 anomaly
                if self._is_amount_column(col_name):
                    self._result.real_anomalies.append(RealAnomaly(
                        table=name,
                        column=col_name,
                        description=f'{name}.{col_name} 类型为 REAL，'
                                     f'转换为 INTEGER 分时可能存在浮点精度风险',
                    ))

    def _probe_transaction_types(self) -> None:
        """统计交易类型分布。"""
        if 'transactions' not in self._result.tables:
            return

        try:
            rows = self._r.fetch_all(
                'SELECT trans_type, COUNT(*) as cnt '
                'FROM transactions GROUP BY trans_type ORDER BY cnt DESC'
            )
            self._result.transaction_type_counts = {
                r['trans_type']: r['cnt'] for r in rows
            }
        except Exception as e:
            self._result.warnings.append(f'交易类型统计失败: {e}')

    def _probe_linked_stock(self) -> None:
        """识别链接证券账户。

        检测信号：
        - accounts.linked_stock_account_id IS NOT NULL
        - accounts.is_system_locked = 1
        - stock_accounts 表存在且有数据
        - group_name 包含 "证券" 或 "stock"
        """
        if 'accounts' not in self._result.tables:
            return

        # 通过 linked_stock_account_id 和 is_system_locked 识别
        try:
            rows = self._r.fetch_all(
                'SELECT id, name, balance, linked_stock_account_id, '
                'is_system_locked, group_name '
                'FROM accounts '
                'WHERE linked_stock_account_id IS NOT NULL '
                '   OR is_system_locked = 1'
            )
            for row in rows:
                self._result.linked_stock_accounts.append(LinkedStockInfo(
                    account_id=row['id'],
                    account_name=row['name'],
                    balance_real=row['balance'],
                    linked_stock_account_id=row['linked_stock_account_id'],
                    is_system_locked=bool(row['is_system_locked']),
                ))
        except Exception as e:
            self._result.warnings.append(f'链接证券账户检测失败: {e}')

        # 检查 stock_accounts 表
        stock_tables = [
            t for t in self._result.tables
            if t.startswith('stock_') and self._result.tables[t].row_count > 0
        ]
        if stock_tables:
            self._result.warnings.append(
                f'检测到 {len(stock_tables)} 个股票相关表有数据: '
                f'{", ".join(stock_tables)}。这些表的数据将归档到 legacy_archive_records。'
            )

        # 通过 group_name 补充识别
        try:
            rows = self._r.fetch_all(
                "SELECT id, name, balance, group_name FROM accounts "
                "WHERE (group_name LIKE '%证券%' OR group_name LIKE '%stock%' "
                "OR group_name LIKE '%投资%' OR group_name LIKE '%invest%')"
            )
            existing_ids = {a.account_id for a in self._result.linked_stock_accounts}
            for row in rows:
                if row['id'] not in existing_ids:
                    self._result.linked_stock_accounts.append(LinkedStockInfo(
                        account_id=row['id'],
                        account_name=row['name'],
                        balance_real=row['balance'],
                        linked_stock_account_id=None,
                        is_system_locked=False,
                    ))
        except Exception:
            pass

    def _probe_balance_diffs(self) -> None:
        """计算账户余额按普通流水重算的差异。

        对于非链接证券账户，余额应等于期初余额 + 所有流水的 signed sum。
        若存在差异，记录到 balance_diffs。

        链接证券账户不进行此检查（其余额由股票估值决定，不可由普通流水重算）。
        """
        if 'accounts' not in self._result.tables or 'transactions' not in self._result.tables:
            return

        linked_ids = {a.account_id for a in self._result.linked_stock_accounts}

        try:
            accounts = self._r.fetch_all('SELECT id, name, balance, type FROM accounts')
        except Exception as e:
            self._result.warnings.append(f'无法读取账户: {e}')
            return

        for acct in accounts:
            acct_id = acct['id']
            acct_name = acct['name']
            stored_balance = acct['balance']
            acct_type = acct['type']

            # 跳过链接证券账户
            if acct_id in linked_ids:
                continue

            # 计算流水重算余额
            computed = self._compute_balance_from_transactions(acct_id, acct_type)
            diff = stored_balance - computed

            if abs(diff) > 0.01:  # 容忍 0.01 元（1 分）
                diff_minor = int(round(diff * 100))
                self._result.balance_diffs.append(BalanceDiff(
                    account_id=acct_id,
                    account_name=acct_name,
                    stored_balance_real=stored_balance,
                    computed_balance_real=computed,
                    diff_real=diff,
                    diff_minor=diff_minor,
                    note=self._balance_diff_note(acct_id, diff, acct_type),
                ))

    def _probe_settings(self) -> None:
        """检测 settings 键，识别敏感键但不展示值。"""
        if 'settings' not in self._result.tables:
            return

        try:
            rows = self._r.fetch_all('SELECT key FROM settings')
        except Exception as e:
            self._result.warnings.append(f'无法读取 settings: {e}')
            return

        all_keys = [r['key'] for r in rows]
        self._result.settings_key_count = len(all_keys)

        for key in all_keys:
            if self._is_sensitive_key(key):
                self._result.settings_sensitive_keys.append(key)

    # ── 内部辅助 ──────────────────────────────────────

    def _compute_balance_from_transactions(
        self, account_id: int, account_type: str
    ) -> float:
        """从旧流水计算账户余额（REAL 精度）。

        旧系统金额为 REAL（元），直接用 REAL 运算。
        符号规则：Asset 账户支出减余额、收入加余额；
        Liability 账户反之。
        """
        # 期初余额
        opening = 0.0
        try:
            row = self._r.fetch_one(
                'SELECT COALESCE(opening_balance, 0) AS ob FROM accounts WHERE id = ?',
                (account_id,),
            )
            if row:
                opening = float(row['ob'])
        except Exception:
            pass

        # 作为转出账户的流水总和
        try:
            out_sum = self._r.fetch_scalar(
                'SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_out_id = ?',
                (account_id,),
            ) or 0.0
        except Exception:
            out_sum = 0.0

        # 作为转入账户的流水总和
        try:
            in_sum = self._r.fetch_scalar(
                'SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_in_id = ?',
                (account_id,),
            ) or 0.0
        except Exception:
            in_sum = 0.0

        is_liability = account_type.lower() in ('liability', 'credit_card', 'credit')

        if is_liability:
            # 负债：支出/转出增加余额，收入/转入减少余额
            return opening + out_sum - in_sum
        else:
            # 资产：支出/转出减少余额，收入/转入增加余额
            return opening - out_sum + in_sum

    @staticmethod
    def _is_amount_column(col_name: str) -> bool:
        """判断列名是否表示金额。"""
        lower = col_name.lower()
        amount_keywords = (
            'amount', 'balance', 'planned', 'budget', 'cash', 'total',
            'price', 'change', 'delta', 'alert', 'fee',
        )
        return any(kw in lower for kw in amount_keywords)

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        """判断 settings 键是否敏感。"""
        lower = key.lower()
        return any(pattern in lower for pattern in _SENSITIVE_KEY_PATTERNS)

    @staticmethod
    def _balance_diff_note(account_id: int, diff: float, acct_type: str) -> str:
        """生成余额差异说明。"""
        if abs(diff) < 0.05:
            return (
                f'轻微差异，可能是 REAL→INTEGER 转换舍入误差 '
                f'（{diff:+.2f} 元 = {int(round(diff * 100)):+d} 分）'
            )
        return (
            f'显著差异 {diff:+.2f} 元（{int(round(diff * 100)):+d} 分），'
            f'可能原因：手动余额调节、股票结算、未记录的流水类型'
        )
