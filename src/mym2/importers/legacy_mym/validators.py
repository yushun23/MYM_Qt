"""迁移验证规则。

验证旧数据向新领域模型的转换是否合法：
- 金额转换精度检查
- 交易类型映射检查
- 账户类型映射检查
- settings 白名单检查
- 股票策略检查
- 余额一致性验证
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from mym2.importers.legacy_mym.migration_plan import (
    PendingConfirmation,
)

logger = logging.getLogger('mym2.importers.legacy_mym.validators')

# ── 已知交易类型映射 ──────────────────────────────────
# 旧类型 → 新 TransactionType（未知类型 → None 触发确认）
_KNOWN_TRANSACTION_TYPES: dict[str, str] = {
    'Expense': 'expense',
    'Income': 'income',
    'Transfer': 'transfer',
    '垫付/借出': 'receivable_advance',
    '收回欠款': 'receivable_repayment',
    'Balance Adjustment': 'balance_adjustment',
    '垫付借出': 'receivable_advance',
    '还款收回': 'receivable_repayment',
}

# ── 已知账户类型映射 ──────────────────────────────────
_KNOWN_ACCOUNT_TYPES: dict[str, str] = {
    'Asset': 'cash',
    'Liability': 'credit_card',
    'Credit': 'credit_card',
    'Receivable': 'receivable',
}

# ── Settings 白名单 ──────────────────────────────────
_SETTINGS_WHITELIST: frozenset[str] = frozenset({
    'theme',
    'language',
    'font_size',
    'font_family',
    'currency_display',
    'date_format',
    'first_day_of_week',
    'backup_path',
    'data_directory',
    'export_path',
    'sort_order',
    'default_account_id',
    'default_category_id',
    'sidebar_collapsed',
})

# ── 强制跳过的 settings 键模式 ──────────────────────
_SETTINGS_BLOCKED_SUBSTRINGS: tuple[str, ...] = (
    'password', 'secret', 'token', 'key', 'api', 'hash',
    'proxy_username', 'proxy_url', 'auth', 'pending_action',
    'session', 'credential', 'license',
)


@dataclass
class AmountConversionResult:
    """单条金额转换结果。"""

    original_real: float
    decimal_value: Decimal
    minor: int
    roundtrip_real: float
    diff_minor: int
    is_acceptable: bool
    note: str = ''


@dataclass
class ValidationReport:
    """迁移验证报告。"""

    amount_conversions: list[AmountConversionResult] = field(default_factory=list)
    unknown_transaction_types: dict[str, int] = field(default_factory=dict)
    unknown_account_types: dict[str, int] = field(default_factory=dict)
    skipped_settings: list[str] = field(default_factory=list)
    allowed_settings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def convert_amount_to_minor(old_real: float | int | str | None) -> AmountConversionResult:
    """将旧库 REAL 金额转为整数分。

    使用 Decimal(str(old_value)) 避免二进制浮点误差，
    记录 ≥1 分的量化差异。

    Args:
        old_real: 旧库金额（REAL / float / int / str）。

    Returns:
        AmountConversionResult 包含转换详情。
    """
    if old_real is None:
        return AmountConversionResult(
            original_real=0.0,
            decimal_value=Decimal('0'),
            minor=0,
            roundtrip_real=0.0,
            diff_minor=0,
            is_acceptable=True,
        )

    # 转换为浮点表示（用于记录原始值）
    original_float = float(old_real)

    # 使用 Decimal + str 避免浮点污染
    try:
        d = Decimal(str(old_real))
    except (InvalidOperation, ValueError):
        return AmountConversionResult(
            original_real=original_float,
            decimal_value=Decimal('0'),
            minor=0,
            roundtrip_real=0.0,
            diff_minor=0,
            is_acceptable=False,
            note=f'Decimal 解析失败: {old_real!r}',
        )

    # 转为分：乘以 100 并量化到整数
    minor_d = (d * 100).quantize(Decimal('1'))
    minor = int(minor_d)

    # 回算：验证转换精度
    roundtrip = float(minor) / 100.0
    diff = original_float - roundtrip
    diff_minor = int(round(diff * 100))

    acceptable = abs(diff_minor) <= 1
    note = ''
    if abs(diff_minor) > 1:
        note = (
            f'量化差异 {diff_minor:+d} 分'
            f'（原 {original_float} → 分 {minor} → 回算 {roundtrip}）'
        )
    elif abs(diff_minor) == 1:
        note = f'舍入差 1 分（原 {original_float}）'

    return AmountConversionResult(
        original_real=original_float,
        decimal_value=d,
        minor=minor,
        roundtrip_real=roundtrip,
        diff_minor=diff_minor,
        is_acceptable=acceptable,
        note=note,
    )


def map_transaction_type(old_type: str) -> str | None:
    """将旧交易类型映射到新 TransactionType。

    已知类型返回对应枚举值，未知类型返回 None。
    调用方应将 None 记录为"需确认"。

    Args:
        old_type: 旧系统交易类型字符串。

    Returns:
        新类型枚举值（str），或 None（未知类型）。
    """
    # 去除首尾空白
    cleaned = old_type.strip() if old_type else ''
    if not cleaned:
        return None
    return _KNOWN_TRANSACTION_TYPES.get(cleaned)


def map_account_type(old_type: str) -> str | None:
    """将旧账户类型映射到新 AccountType。

    Args:
        old_type: 旧系统账户类型字符串。

    Returns:
        新类型枚举值（str），或 None（未知类型）。
    """
    cleaned = old_type.strip() if old_type else ''
    if not cleaned:
        return None
    return _KNOWN_ACCOUNT_TYPES.get(cleaned)


def is_settings_allowed(key: str) -> bool:
    """检查 settings 键是否在白名单中。

    Args:
        key: settings 键名。

    Returns:
        True 如果允许迁移。
    """
    key_lower = key.strip().lower()
    # 先检查黑名单
    for blocked in _SETTINGS_BLOCKED_SUBSTRINGS:
        if blocked in key_lower:
            return False
    return key_lower in _SETTINGS_WHITELIST


def is_settings_blocked(key: str) -> bool:
    """检查 settings 键是否必须跳过（含敏感信息）。

    Args:
        key: settings 键名。

    Returns:
        True 如果必须跳过。
    """
    key_lower = key.strip().lower()
    return any(blocked in key_lower for blocked in _SETTINGS_BLOCKED_SUBSTRINGS)


def validate_stock_strategy(strategy: str) -> bool:
    """验证股票处理策略是否合法。

    Args:
        strategy: 策略名。

    Returns:
        True 如果合法。
    """
    return strategy in ('historical_snapshot', 'archive_only', 'skip')


def build_balance_confirmation(
    account_id: int,
    account_name: str,
    account_type: str,
    legacy_balance_real: float,
    recomputed_minor: int,
) -> PendingConfirmation:
    """为余额差异账户构建确认项。

    Args:
        account_id: 旧账户 ID。
        account_name: 账户名。
        account_type: 账户类型。
        legacy_balance_real: 旧余额（REAL）。
        recomputed_minor: 重算余额（分）。

    Returns:
        PendingConfirmation 对象。
    """
    legacy_minor = convert_amount_to_minor(legacy_balance_real).minor
    diff = legacy_minor - recomputed_minor

    return PendingConfirmation(
        category='余额差异',
        item=f'{account_name} (ID={account_id}, type={account_type})',
        reason=(
            f'旧余额 {legacy_balance_real:.2f} 元'
            f'（{legacy_minor} 分）'
            f'与流水重算 {recomputed_minor} 分'
            f'相差 {diff:+d} 分'
        ),
        suggestion=(
            '若为链接证券账户，将按 historical_snapshot 策略'
            '创建不可编辑历史投资资产快照，并生成调节流水补齐差额。'
            '若非链接证券账户，请确认是否有未记录的余额调节。'
        ),
    )
