"""服务层参数验证器。

所有验证器返回 None 表示通过；不通过则抛出 ValueError。
"""

from __future__ import annotations

from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import (
    AccountType,
    CategoryType,
    TransactionType,
)


def validate_account_writable(account: Account) -> None:
    """验证账户可写入。

    Raises:
        ValueError: 账户停用、不可编辑或被锁定。
    """
    if not account.is_enabled:
        raise ValueError(f'账户 "{account.name}" 已停用，不可写入')
    if not account.is_editable:
        raise ValueError(f'账户 "{account.name}" 不可编辑（历史快照）')
    if account.is_locked:
        raise ValueError(f'账户 "{account.name}" 已锁定，不可写入')


def validate_account_not_receivable(account: Account) -> None:
    """验证账户不是应收账户（应收只能由应收专用服务写入）。

    Raises:
        ValueError: 账户类型为 receivable。
    """
    if account.type == AccountType.RECEIVABLE:
        raise ValueError(
            f'账户 "{account.name}" 为应收账户，只能由应收专用服务写入'
        )


def validate_category_compatible(
    category: Category | None,
    transaction_type: TransactionType,
) -> None:
    """验证分类与交易类型相容。

    - expense 类型必须关联 expense 分类
    - income 类型必须关联 income 分类
    - transfer / balance_adjustment / historical_investment_settlement 不应有关联分类
    - receivable_advance / receivable_repayment 不通过 LedgerService 写入

    Raises:
        ValueError: 分类不兼容。
    """
    if transaction_type in (
        TransactionType.TRANSFER,
        TransactionType.BALANCE_ADJUSTMENT,
        TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT,
    ):
        if category is not None:
            raise ValueError(
                f'{transaction_type.value} 类型不应关联分类'
            )
        return

    if transaction_type == TransactionType.EXPENSE:
        if category is None:
            raise ValueError('支出交易必须指定分类')
        if category.type != CategoryType.EXPENSE:
            raise ValueError(
                f'支出交易必须关联支出分类，'
                f'但分类 "{category.name}" 类型为 {category.type}'
            )

    elif transaction_type == TransactionType.INCOME:
        if category is None:
            raise ValueError('收入交易必须指定分类')
        if category.type != CategoryType.INCOME:
            raise ValueError(
                f'收入交易必须关联收入分类，'
                f'但分类 "{category.name}" 类型为 {category.type}'
            )


def validate_transaction_editable(transaction: Transaction) -> None:
    """验证流水可编辑/删除。

    Raises:
        ValueError: 流水被锁定或为历史结算。
    """
    if transaction.is_locked:
        raise ValueError('该流水已锁定，不可编辑/删除')
    if transaction.type == TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT:
        raise ValueError('历史投资结算流水不可编辑/删除')


def validate_account_for_transaction_type(
    account: Account,
    transaction_type: TransactionType,
    role: str,  # 'out' | 'in'
) -> None:
    """验证账户类型与交易类型相容。

    例如 credit_card 账户用于 income 时是还款（合法），
    但不能用于 receivable 交易（应收只能由应收服务写入）。

    Raises:
        ValueError: 账户类型不兼容。
    """
    validate_account_writable(account)

    if transaction_type in (
        TransactionType.RECEIVABLE_ADVANCE,
        TransactionType.RECEIVABLE_REPAYMENT,
    ):
        # 应收交易必须有 receivable 账户参与
        if role == 'in' and account.type != AccountType.RECEIVABLE:
            raise ValueError(
                f'应收垫付的 target 账户必须为 receivable 类型，'
                f'但 "{account.name}" 类型为 {account.type}'
            )
        if role == 'out' and account.type == AccountType.RECEIVABLE:
            pass  # receivable_repayment 时 out 是 receivable
        elif role == 'out' and account.type != AccountType.RECEIVABLE:
            if transaction_type == TransactionType.RECEIVABLE_ADVANCE:
                pass  # advance 时 out 是普通资产
            else:
                raise ValueError(
                    '应收还款的 source 账户必须为 receivable 类型'
                )
    else:
        validate_account_not_receivable(account)
