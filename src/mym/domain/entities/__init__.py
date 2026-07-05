"""Domain entities – all ORM models must be imported here for Alembic autogenerate."""

from mym.domain.entities.account import Account
from mym.domain.entities.ai_ import ChatSession, ChatMessage
from mym.domain.entities.audit import AuditLog
from mym.domain.entities.budget import BudgetPeriod, BudgetLine
from mym.domain.entities.category import Category
from mym.domain.entities.import_ import ImportIssue, ImportJob, LegacyIdMap
from mym.domain.entities.investment import (
    InvestmentAccount,
    InvestmentCashFlow,
    InvestmentSettlement,
    InvestmentTrade,
    QuoteSnapshot,
    Security,
)
from mym.domain.entities.receivable import ReceivableCase, ReceivableEvent
from mym.domain.entities.setting import AppSetting
from mym.domain.entities.transaction import Transaction, TransactionLine

__all__ = [
    "Account",
    "AuditLog",
    "AppSetting",
    "BudgetPeriod",
    "BudgetLine",
    "Category",
    "ChatSession",
    "ChatMessage",
    "ImportIssue",
    "ImportJob",
    "InvestmentAccount",
    "InvestmentCashFlow",
    "InvestmentSettlement",
    "InvestmentTrade",
    "LegacyIdMap",
    "QuoteSnapshot",
    "ReceivableCase",
    "ReceivableEvent",
    "Security",
    "Transaction",
    "TransactionLine",
]
