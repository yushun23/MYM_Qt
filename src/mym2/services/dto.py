"""服务层数据传输对象（DTO）与验证器。

定义创建/编辑流水的请求结构，以及参数验证逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mym2.domain.enums import TransactionType


@dataclass(slots=True)
class CreateAccountDTO:
    """创建账户的请求。"""

    name: str
    type: str  # AccountType 值
    group: str | None = None
    opening_balance_minor: int = 0
    currency: str = "CNY"
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("账户名称不能为空")
        if len(self.name) > 100:
            raise ValueError("账户名称不能超过 100 个字符")
        if self.opening_balance_minor < 0:
            raise ValueError("期初余额不能为负数")
        from mym2.domain.enums import AccountType
        valid_types = {t.value for t in AccountType}
        if self.type not in valid_types:
            raise ValueError(f"无效的账户类型: {self.type}")


@dataclass(slots=True)
class UpdateAccountDTO:
    """编辑账户的请求。所有字段可选。"""

    name: str | None = None
    type: str | None = None
    group: str | None = None
    opening_balance_minor: int | None = None
    currency: str | None = None
    notes: str | None = None
    is_enabled: bool | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            if not self.name.strip():
                raise ValueError("账户名称不能为空")
            if len(self.name) > 100:
                raise ValueError("账户名称不能超过 100 个字符")
        if self.opening_balance_minor is not None and self.opening_balance_minor < 0:
            raise ValueError("期初余额不能为负数")
        if self.type is not None:
            from mym2.domain.enums import AccountType
            valid_types = {t.value for t in AccountType}
            if self.type not in valid_types:
                raise ValueError(f"无效的账户类型: {self.type}")


@dataclass(slots=True)
class CreateCategoryDTO:
    """创建分类的请求。"""

    name: str
    type: str  # CategoryType 值
    parent_id: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int = 0

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("分类名称不能为空")
        if len(self.name) > 100:
            raise ValueError("分类名称不能超过 100 个字符")
        from mym2.domain.enums import CategoryType
        valid_types = {t.value for t in CategoryType}
        if self.type not in valid_types:
            raise ValueError(f"无效的分类类型: {self.type}")


@dataclass(slots=True)
class UpdateCategoryDTO:
    """编辑分类的请求。所有字段可选。"""

    name: str | None = None
    type: str | None = None
    parent_id: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    is_enabled: bool | None = None

    def __post_init__(self) -> None:
        if self.name is not None:
            if not self.name.strip():
                raise ValueError("分类名称不能为空")
            if len(self.name) > 100:
                raise ValueError("分类名称不能超过 100 个字符")
        if self.type is not None:
            from mym2.domain.enums import CategoryType
            valid_types = {t.value for t in CategoryType}
            if self.type not in valid_types:
                raise ValueError(f"无效的分类类型: {self.type}")


@dataclass(slots=True)
class CreateTransactionDTO:
    """创建流水的请求。

    金额方向由 transaction_type 决定，amount_minor 始终为正。
    """

    transaction_type: TransactionType
    transaction_date: date
    account_out_id: str
    amount_minor: int
    category_id: str | None = None
    account_in_id: str | None = None
    note: str | None = None
    source: str = 'manual'

    def __post_init__(self) -> None:
        from mym2.domain.money import validate_positive_amount_minor

        validate_positive_amount_minor(self.amount_minor)
        if not self.account_out_id:
            raise ValueError('account_out_id 不能为空')
        if self.transaction_type in (
            TransactionType.TRANSFER,
            TransactionType.RECEIVABLE_ADVANCE,
            TransactionType.RECEIVABLE_REPAYMENT,
        ) and not self.account_in_id:
                raise ValueError(
                    f'{self.transaction_type.value} 类型必须提供 account_in_id'
                )
        if self.transaction_type == TransactionType.TRANSFER:
            if self.account_out_id == self.account_in_id:
                raise ValueError('转账的两个账户不能相同')
            if self.category_id is not None:
                raise ValueError('转账不支持关联分类')


@dataclass(slots=True)
class UpdateTransactionDTO:
    """编辑流水的请求。

    所有字段可选；None 表示不修改。
    """

    transaction_date: date | None = None
    amount_minor: int | None = None
    category_id: str | None = None
    account_in_id: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.amount_minor is not None:
            from mym2.domain.money import validate_positive_amount_minor

            validate_positive_amount_minor(self.amount_minor)
