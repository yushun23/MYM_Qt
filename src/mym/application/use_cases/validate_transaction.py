"""ValidateTransactionUseCase – validates transaction data before writing."""

from dataclasses import dataclass, field
from decimal import Decimal

from mym.application.dto.transaction_dto import CreateTransactionDTO, TransactionLineDTO
from mym.domain.enums import AccountType, CategoryType
from mym.infrastructure.repositories.account_repo import AccountRepository
from mym.infrastructure.repositories.category_repo import CategoryRepository


@dataclass
class ValidationResult:
    """Result of transaction validation."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)


class ValidateTransactionUseCase:
    """Validates a transaction before it is created.

    Convention: ALL signed_amount values are positive (absolute amounts).
    Conservation: SUM(debit amounts) == SUM(credit amounts).
    """

    def __init__(
        self,
        account_repo: AccountRepository,
        category_repo: CategoryRepository,
    ) -> None:
        self._account_repo = account_repo
        self._category_repo = category_repo

    def execute(self, dto: CreateTransactionDTO) -> ValidationResult:
        result = ValidationResult()

        # Check lines exist
        if not dto.lines:
            result.is_valid = False
            result.errors.append("交易至少需要一条明细行")
            return result

        # Validate each line
        for i, line in enumerate(dto.lines):
            self._validate_line(line, i, dto.business_type, result)

        # Check amount conservation: sum of debits == sum of credits
        debit_total = sum(
            line.signed_amount for line in dto.lines if line.role == "debit"
        )
        credit_total = sum(
            line.signed_amount for line in dto.lines if line.role == "credit"
        )
        if abs(debit_total - credit_total) > Decimal("0.005"):
            result.is_valid = False
            result.errors.append(
                f"交易金额不守恒: 借方={debit_total}, 贷方={credit_total}"
            )

        # Business-type specific checks
        if dto.business_type == "transfer":
            self._validate_transfer(dto, result)

        return result

    def _validate_transfer(
        self, dto: CreateTransactionDTO, result: ValidationResult
    ) -> None:
        """Transfer-specific validation."""
        account_ids = {line.account_id for line in dto.lines}
        if len(account_ids) < 2:
            result.is_valid = False
            result.errors.append("转账需要不同的转出和转入账户")

    def _validate_line(
        self,
        line: TransactionLineDTO,
        index: int,
        business_type: str,
        result: ValidationResult,
    ) -> None:
        prefix = f"第{index + 1}行: "

        # Amount must be positive (absolute value convention)
        if line.signed_amount <= Decimal("0"):
            result.is_valid = False
            result.errors.append(f"{prefix}金额必须大于0")

        # Account must exist and be enabled
        account = self._account_repo.get_by_id(line.account_id)
        if account is None:
            result.is_valid = False
            result.errors.append(f"{prefix}账户(id={line.account_id})不存在")
            return

        if account.is_deleted:
            result.is_valid = False
            result.errors.append(f"{prefix}账户'{account.name}'已删除")
        elif not account.is_enabled:
            result.is_valid = False
            result.errors.append(f"{prefix}账户'{account.name}'已禁用")
        elif account.is_archived:
            result.is_valid = False
            result.errors.append(f"{prefix}账户'{account.name}'已归档")

        # Normal entries cannot use receivable or investment accounts
        if business_type not in ("lend", "recover", "stock_profit", "stock_loss", "balance_adjustment"):
            if account.account_type == AccountType.RECEIVABLE:
                result.is_valid = False
                result.errors.append(f"{prefix}普通记账不能使用应收账户'{account.name}'")
            elif account.account_type == AccountType.INVESTMENT_LINKED:
                result.is_valid = False
                result.errors.append(f"{prefix}普通记账不能使用投资联动账户'{account.name}'")

        # Category validation for income/expense business types
        if business_type in ("income", "expense", "stock_profit", "stock_loss"):
            if line.category_id is None:
                result.is_valid = False
                result.errors.append(f"{prefix}需要指定分类")
            else:
                category = self._category_repo.get_by_id(line.category_id)
                if category is None:
                    result.is_valid = False
                    result.errors.append(f"{prefix}分类(id={line.category_id})不存在")
                elif not category.is_enabled:
                    result.is_valid = False
                    result.errors.append(f"{prefix}分类'{category.name}'已禁用")
                elif business_type in ("income", "stock_profit") and category.category_type not in (CategoryType.INCOME, CategoryType.SYSTEM):
                    result.is_valid = False
                    result.errors.append(f"{prefix}收入交易需要收入分类")
                elif business_type in ("expense", "stock_loss") and category.category_type not in (CategoryType.EXPENSE, CategoryType.SYSTEM):
                    result.is_valid = False
                    result.errors.append(f"{prefix}支出交易需要支出分类")
