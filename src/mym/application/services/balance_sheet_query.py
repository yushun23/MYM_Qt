"""BalanceSheetQueryService – historical as-of-date balance sheet generation."""

import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym.application.dto.report_dto import BalanceSheetSnapshot
from mym.domain.entities.account import Account
from mym.domain.entities.transaction import Transaction, TransactionLine
from mym.domain.enums import AccountType, TransactionRole, TransactionStatus

logger = logging.getLogger(__name__)


class InvestmentValuationProvider:
    """Interface for providing investment valuations at a given date.

    To be implemented by P26/P27 (stock module) – provides historical
    market value of investment-linked accounts.
    """

    def get_valuation(self, account_id: int, as_of_date: date) -> Decimal | None:
        """Return market valuation for an investment account at as_of_date,
        or None if data is unavailable."""
        return None

    def get_total_valuation(self, as_of_date: date) -> Decimal | None:
        """Return total market valuation for all investment accounts at as_of_date,
        or None if data is unavailable."""
        return None

    def get_valuation_warning(self, as_of_date: date) -> str:
        """Return warning message if valuation data is incomplete."""
        if self.get_total_valuation(as_of_date) is None:
            return "估值数据不足：投资模块尚未提供历史行情数据，投资资产显示为账面成本"
        return ""


class BalanceSheetQueryService:
    """Read-only service for balance sheet generation at a given date."""

    def __init__(
        self,
        session: Session,
        valuation_provider: InvestmentValuationProvider | None = None,
    ) -> None:
        self._session = session
        self._valuation_provider = valuation_provider or InvestmentValuationProvider()

    def get_balance_sheet(self, as_of_date: date) -> BalanceSheetSnapshot:
        """Generate balance sheet at the specified as-of date.

        Balances are computed from opening_balance + all posted transactions
        up to (and including) as_of_date. This is NOT the current cached balance.
        """
        snapshot = BalanceSheetSnapshot(as_of_date=as_of_date)

        accounts = self._session.execute(
            select(Account).where(
                Account.is_deleted == False,  # noqa: E712
                Account.is_archived == False,  # noqa: E712
            )
        ).scalars().all()

        asset_groups: dict[str, list[dict]] = {}
        liability_groups: dict[str, list[dict]] = {}
        total_assets = Decimal("0")
        total_liabilities = Decimal("0")
        cash_total = Decimal("0")
        receivable_total = Decimal("0")

        for acc in accounts:
            balance = self._compute_historical_balance(acc.id, acc.opening_balance, as_of_date)

            entry = {
                "id": acc.id,
                "name": acc.name,
                "balance": str(balance),
                "currency": acc.currency,
            }

            if acc.account_type == AccountType.LIABILITY:
                group = acc.group_name or "负债"
                liability_groups.setdefault(group, []).append(entry)
                total_liabilities += abs(balance)
            elif acc.account_type == AccountType.RECEIVABLE:
                group = acc.group_name or "应收款"
                asset_groups.setdefault(group, []).append(entry)
                receivable_total += balance
                total_assets += balance
            elif acc.account_type == AccountType.INVESTMENT_LINKED:
                # Investment accounts: display book value; valuation from provider
                val = self._valuation_provider.get_valuation(acc.id, as_of_date)
                entry["book_balance"] = str(balance)
                if val is not None:
                    entry["market_value"] = str(val)
                    entry["balance"] = str(val)
                    total_assets += val
                else:
                    entry["market_value"] = "—"
                    entry["balance"] = str(balance)
                    total_assets += balance
                group = acc.group_name or "投资"
                asset_groups.setdefault(group, []).append(entry)
            else:
                group = acc.group_name or "资产"
                asset_groups.setdefault(group, []).append(entry)
                cash_total += balance
                total_assets += balance

        snapshot.total_assets = total_assets
        snapshot.total_liabilities = total_liabilities
        snapshot.net_worth = total_assets - total_liabilities
        snapshot.cash_balance = cash_total
        snapshot.receivable_balance = receivable_total
        snapshot.investment_estimated = Decimal("0")
        snapshot.account_groups = [
            {"group": k, "accounts": v} for k, v in sorted(asset_groups.items())
        ]
        snapshot.liability_groups = [
            {"group": k, "accounts": v} for k, v in sorted(liability_groups.items())
        ]
        snapshot.investment_valuation_warning = self._valuation_provider.get_valuation_warning(
            as_of_date
        )

        return snapshot

    def _compute_historical_balance(
        self, account_id: int, opening_balance: Decimal, as_of_date: date
    ) -> Decimal:
        """Compute balance = opening_balance + Σ posted line effects up to as_of_date."""
        lines = self._session.execute(
            select(TransactionLine)
            .join(Transaction)
            .where(
                TransactionLine.account_id == account_id,
                Transaction.status == TransactionStatus.POSTED,
                Transaction.transaction_date <= as_of_date,
            )
        ).scalars().all()

        balance = opening_balance
        for line in lines:
            balance += line.signed_amount

        return balance
