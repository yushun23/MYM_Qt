"""余额服务 — 负责从流水重算账户余额。

金额方向规则：
- 资产账户（cash/bank/investment_snapshot/receivable）：
  支出/转出 → 余额减少；收入/转入 → 余额增加。
- 负债账户（credit_card）：
  消费/转出 → 余额增加（欠款增多）；还款/转入 → 余额减少（欠款减少）。
- balance_adjustment / historical_investment_settlement：
  直接累加到 account_out 余额。
- income 交易当 account_out == account_in 时，仅计入一次（外部资金流入）。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import (
    TransactionType,
    is_asset_account,
)

logger = logging.getLogger('mym2.services.balance_service')


class BalanceService:
    """余额重算服务。

    不从外部依赖 Repository；直接在传入的 Session 上执行查询和更新。
    """

    def __init__(self) -> None:
        pass

    # ── 公开 API ──────────────────────────────────────

    def recalculate_account(self, session: Session, account_id: str) -> int:
        """重算单个账户余额并持久化。

        Args:
            session: 活动数据库会话（需在事务中）。
            account_id: 账户 ID。

        Returns:
            新余额（整数分）。
        """
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'账户不存在: {account_id}')

        new_balance = self._compute_balance(session, account)
        account.current_balance_minor = new_balance
        session.flush([account])
        return new_balance

    def recalculate_accounts(
        self, session: Session, account_ids: list[str]
    ) -> dict[str, int]:
        """重算多个账户余额并持久化。

        Args:
            session: 活动数据库会话。
            account_ids: 账户 ID 列表。

        Returns:
            {account_id: new_balance_minor} 映射。
        """
        accounts = list(
            session.scalars(
                select(Account).where(Account.id.in_(account_ids))
            )
        )
        result: dict[str, int] = {}
        for account in accounts:
            new_balance = self._compute_balance(session, account)
            account.current_balance_minor = new_balance
            result[account.id] = new_balance
        session.flush()
        return result

    # ── 内部计算逻辑 ──────────────────────────────────

    def _compute_balance(self, session: Session, account: Account) -> int:
        """从流水计算账户余额。

        余额 = opening_balance_minor + Σ 每笔流水的 signed contribution。
        """
        balance = account.opening_balance_minor
        transactions = self._get_account_transactions(session, account.id)

        for tx in transactions:
            balance += self._signed_contribution(tx, account.id, account.type)

        return balance

    @staticmethod
    def _get_account_transactions(
        session: Session, account_id: str
    ) -> list[Transaction]:
        """获取影响指定账户的所有流水。"""
        return list(
            session.scalars(
                select(Transaction).where(
                    (Transaction.account_out_id == account_id)
                    | (Transaction.account_in_id == account_id)
                ).order_by(Transaction.transaction_date, Transaction.created_at)
            )
        )

    @staticmethod
    def _signed_contribution(
        tx: Transaction, account_id: str, account_type: str
    ) -> int:
        """计算一笔流水对指定账户的符号化贡献（分）。

        返回正数表示增加余额，负数表示减少余额。
        """
        is_asset = is_asset_account(account_type)


        # 余额调节 / 历史投资结算：直接累加到 account_out
        if tx.type in (
            TransactionType.BALANCE_ADJUSTMENT,
            TransactionType.HISTORICAL_INVESTMENT_SETTLEMENT,
        ):
            if tx.account_out_id == account_id:
                return tx.amount_minor
            return 0

        # 收入交易：当 account_out == account_in 时视为外部资金流入，
        # 仅按 account_in 方向计算一次（避免双重计数）
        if tx.type == TransactionType.INCOME and tx.account_out_id == tx.account_in_id:
            if tx.account_in_id == account_id:
                return tx.amount_minor if is_asset else -tx.amount_minor
            return 0

        # 普通流水：按资金流向和账户性质决定符号
        contribution = 0
        if tx.account_out_id == account_id:
            contribution += -tx.amount_minor if is_asset else tx.amount_minor
        if tx.account_in_id == account_id:
            contribution += tx.amount_minor if is_asset else -tx.amount_minor
        return contribution
