"""Domain enumerations for MYM."""

from enum import Enum, StrEnum


class AccountType(str, Enum):
    """Types of accounts in the system."""

    ASSET = "asset"
    LIABILITY = "liability"
    RECEIVABLE = "receivable"
    INVESTMENT_LINKED = "investment_linked"

    @property
    def is_system_locked(self) -> bool:
        """Whether this account type is system-locked (not user-editable)."""
        return self in (AccountType.RECEIVABLE, AccountType.INVESTMENT_LINKED)


class CategoryType(str, Enum):
    """Types of categories."""

    INCOME = "income"
    EXPENSE = "expense"
    SYSTEM = "system"


class TransactionSource(str, Enum):
    """Source of a transaction."""

    MANUAL = "manual"
    IMPORT = "import"
    MIGRATION = "migration"
    AI = "ai"
    SYSTEM = "system"


class TransactionStatus(str, Enum):
    """Status of a transaction."""

    DRAFT = "draft"
    POSTED = "posted"
    VOID = "void"


class TransactionRole(str, Enum):
    """Role of a transaction line."""

    DEBIT = "debit"  # 借方
    CREDIT = "credit"  # 贷方


class ImportStatus(str, Enum):
    """Status of an import job."""

    PENDING = "pending"
    PREVIEWING = "previewing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ImportIssueSeverity(str, Enum):
    """Severity of an import issue."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ReceivableStatus(str, Enum):
    """Status of a receivable case."""

    PENDING = "pending"
    PARTIALLY_RECOVERED = "partially_recovered"
    FULLY_RECOVERED = "fully_recovered"
    WRITTEN_OFF = "written_off"


class BudgetStatus(str, Enum):
    """Status of a budget period."""

    OPEN = "open"
    CLOSED = "closed"


class InvestmentModuleStatus(str, Enum):
    """Visibility status of the investment module."""

    ENABLED = "enabled"
    HIDDEN = "hidden"
    ARCHIVED = "archived"


class CashFlowType(str, Enum):
    """Type of investment cash flow."""

    INITIAL = "initial"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    ADJUSTMENT = "adjustment"
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    TAX = "tax"


class ActionRiskLevel(str, Enum):
    """Risk level of an AI action."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
