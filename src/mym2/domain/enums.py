"""MYM2 领域枚举。

定义账户类型、交易类型、分类类型、审计操作等核心枚举。
"""

from __future__ import annotations

from enum import StrEnum


class TransactionType(StrEnum):
    """交易类型枚举。

    每个类型决定流水如何影响账户余额。金额始终为正整数（分）；
    方向由交易类型与账户性质（资产/负债）共同决定。
    """

    EXPENSE = 'expense'
    INCOME = 'income'
    TRANSFER = 'transfer'
    RECEIVABLE_ADVANCE = 'receivable_advance'
    RECEIVABLE_REPAYMENT = 'receivable_repayment'
    BALANCE_ADJUSTMENT = 'balance_adjustment'
    HISTORICAL_INVESTMENT_SETTLEMENT = 'historical_investment_settlement'


class AccountType(StrEnum):
    """账户类型枚举。"""

    CASH = 'cash'
    BANK = 'bank'
    CREDIT_CARD = 'credit_card'
    INVESTMENT_SNAPSHOT = 'investment_snapshot'
    RECEIVABLE = 'receivable'


class CategoryType(StrEnum):
    """分类类型枚举。"""

    EXPENSE = 'expense'
    INCOME = 'income'
    SYSTEM = 'system'


class AuditAction(StrEnum):
    """审计操作类型。"""

    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'


# ── 辅助判断函数 ──────────────────────────────────────

_ASSET_TYPES: frozenset[str] = frozenset({
    AccountType.CASH,
    AccountType.BANK,
    AccountType.INVESTMENT_SNAPSHOT,
    AccountType.RECEIVABLE,
})

_LIABILITY_TYPES: frozenset[str] = frozenset({
    AccountType.CREDIT_CARD,
})


def is_asset_account(account_type: str) -> bool:
    """判断账户是否为资产类。"""
    return account_type in _ASSET_TYPES


def is_liability_account(account_type: str) -> bool:
    """判断账户是否为负债类。"""
    return account_type in _LIABILITY_TYPES
