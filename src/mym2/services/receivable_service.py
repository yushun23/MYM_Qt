"""应收服务 — 应收垫付/还款的唯一写入口。

所有应收相关流水（receivable_advance / receivable_repayment）
只能通过本服务创建。本服务内部委托 LedgerService 执行写操作。

规则：
- 债务人 = type=receivable 的账户
- 垫付/借出：资金从现金/银行卡 → 应收账户 (receivable_advance)
- 收回欠款：资金从应收账户 → 收款账户 (receivable_repayment)
- 普通流水编辑器不得将支出/收入写入应收账户
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType, TransactionType
from mym2.domain.money import Money, validate_positive_amount_minor
from mym2.services.balance_service import BalanceService
from mym2.services.dto import CreateTransactionDTO
from mym2.services.ledger_service import LedgerService

logger = logging.getLogger('mym2.services.receivable_service')


def _cents_to_yuan(minor: int) -> str:
    """整数分 → 元显示（保留两位小数）。"""
    return Money(minor=minor).format()



# ── DTOs ──────────────────────────────────────────────


@dataclass(slots=True)
class AdvanceDTO:
    """垫付/借出请求。"""

    debtor_account_id: str  # receivable 类型的账户
    funding_account_id: str  # 现金/银行卡等
    amount_minor: int
    transaction_date: date
    note: str | None = None

    def __post_init__(self) -> None:
        validate_positive_amount_minor(self.amount_minor)
        if not self.debtor_account_id:
            raise ValueError('债务人账户不能为空')
        if not self.funding_account_id:
            raise ValueError('资金来源账户不能为空')
        if self.debtor_account_id == self.funding_account_id:
            raise ValueError('债务人账户与资金来源账户不能相同')


@dataclass(slots=True)
class RepayDTO:
    """收回欠款请求。"""

    debtor_account_id: str  # receivable 类型的账户
    collection_account_id: str  # 收款账户（现金/银行卡等）
    amount_minor: int
    transaction_date: date
    note: str | None = None

    def __post_init__(self) -> None:
        validate_positive_amount_minor(self.amount_minor)
        if not self.debtor_account_id:
            raise ValueError('债务人账户不能为空')
        if not self.collection_account_id:
            raise ValueError('收款账户不能为空')
        if self.debtor_account_id == self.collection_account_id:
            raise ValueError('债务人账户与收款账户不能相同')


@dataclass(slots=True)
class ReceivableSummary:
    """债务人应收汇总。"""

    account_id: str
    account_name: str
    balance_minor: int
    pending_count: int  # 未结清的垫付笔数
    total_advanced_minor: int  # 累计垫付金额
    total_repaid_minor: int  # 累计还款金额

    @property
    def balance_display(self) -> str:
        return _cents_to_yuan(self.balance_minor)

    @property
    def total_advanced_display(self) -> str:
        return _cents_to_yuan(self.total_advanced_minor)

    @property
    def total_repaid_display(self) -> str:
        return _cents_to_yuan(self.total_repaid_minor)


@dataclass(slots=True)
class ReceivableTransactionView:
    """应收流水视图（用于 UI 展示）。"""

    transaction_id: str
    transaction_type: str  # receivable_advance / receivable_repayment
    transaction_date: date
    debtor_account_id: str
    debtor_account_name: str
    counter_account_id: str | None  # 对方账户（资金来源/收款账户）
    counter_account_name: str | None
    amount_minor: int
    note: str | None
    is_deleted: bool = False

    @property
    def amount_display(self) -> str:
        return _cents_to_yuan(self.amount_minor)

    @property
    def is_advance(self) -> bool:
        return self.transaction_type == TransactionType.RECEIVABLE_ADVANCE

    @property
    def is_repayment(self) -> bool:
        return self.transaction_type == TransactionType.RECEIVABLE_REPAYMENT


# ── Service ───────────────────────────────────────────


class ReceivableService:
    """应收服务。

    委托 LedgerService 执行实际写操作，仅负责应收业务的
    逻辑编排、查询和展示视图构建。
    """

    def __init__(
        self,
        ledger_service: LedgerService | None = None,
        balance_service: BalanceService | None = None,
    ) -> None:
        self._ledger = ledger_service or LedgerService()
        self._balance = balance_service or BalanceService()

    # ═══════════════════════════════════════════════════
    #  写操作
    # ═══════════════════════════════════════════════════

    def advance(
        self, session: Session, dto: AdvanceDTO
    ) -> Transaction:
        """垫付/借出：从资金账户转入应收账户。

        Args:
            session: 活动会话（需在事务中）。
            dto: 垫付请求。

        Returns:
            创建的 Transaction 实例。

        Raises:
            ValueError: 验证失败。
        """
        self._validate_debtor(session, dto.debtor_account_id)
        self._validate_funding_source(session, dto.funding_account_id)

        tx_dto = CreateTransactionDTO(
            transaction_type=TransactionType.RECEIVABLE_ADVANCE,
            transaction_date=dto.transaction_date,
            account_out_id=dto.funding_account_id,
            account_in_id=dto.debtor_account_id,
            amount_minor=dto.amount_minor,
            note=dto.note,
            source='manual',
        )
        tx = self._ledger.create_transaction(session, tx_dto)
        logger.info(
            '垫付: %s → %s, %d 分',
            dto.funding_account_id, dto.debtor_account_id, dto.amount_minor,
        )
        return tx

    def repay(
        self, session: Session, dto: RepayDTO
    ) -> Transaction:
        """收回欠款：从应收账户转回收款账户。

        支持部分还款（amount_minor < 当前应收余额）和全部还款。

        Args:
            session: 活动会话（需在事务中）。
            dto: 还款请求。

        Returns:
            创建的 Transaction 实例。

        Raises:
            ValueError: 验证失败（余额不足等）。
        """
        self._validate_debtor(session, dto.debtor_account_id)
        self._validate_collection_target(session, dto.collection_account_id)

        # 验证还款金额不超过应收余额
        balance = self.get_receivable_balance(session, dto.debtor_account_id)
        if dto.amount_minor > balance:
            raise ValueError(
                f'还款金额 ({_cents_to_yuan(dto.amount_minor)}) '
                f'超过当前应收余额 ({_cents_to_yuan(balance)})'
            )

        tx_dto = CreateTransactionDTO(
            transaction_type=TransactionType.RECEIVABLE_REPAYMENT,
            transaction_date=dto.transaction_date,
            account_out_id=dto.debtor_account_id,
            account_in_id=dto.collection_account_id,
            amount_minor=dto.amount_minor,
            note=dto.note,
            source='manual',
        )
        tx = self._ledger.create_transaction(session, tx_dto)
        logger.info(
            '还款: %s → %s, %d 分',
            dto.debtor_account_id, dto.collection_account_id, dto.amount_minor,
        )
        return tx

    def delete_receivable_transaction(
        self, session: Session, transaction_id: str
    ) -> None:
        """删除一笔应收相关流水。

        只允许删除 receivable_advance / receivable_repayment 类型。

        Args:
            session: 活动会话。
            transaction_id: 流水 ID。

        Raises:
            ValueError: 流水不存在或类型不符。
        """
        tx = session.get(Transaction, transaction_id)
        if tx is None:
            raise ValueError(f'流水不存在: {transaction_id}')
        if tx.type not in (
            TransactionType.RECEIVABLE_ADVANCE,
            TransactionType.RECEIVABLE_REPAYMENT,
        ):
            raise ValueError(
                f'流水 {transaction_id} 不是应收相关流水，'
                f'类型为 {tx.type}'
            )
        self._ledger.delete_transaction(session, transaction_id)

    # ═══════════════════════════════════════════════════
    #  查询
    # ═══════════════════════════════════════════════════

    def get_receivable_accounts(self, session: Session) -> list[Account]:
        """获取所有 receivable 类型账户。"""
        return list(
            session.scalars(
                select(Account)
                .where(Account.type == AccountType.RECEIVABLE)
                .where(Account.is_enabled)
                .order_by(Account.name)
            )
        )

    def get_receivable_balance(
        self, session: Session, account_id: str
    ) -> int:
        """获取应收账户当前余额（整数分）。

        余额 > 0 表示仍有未收回的欠款。
        """
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'账户不存在: {account_id}')
        if account.type != AccountType.RECEIVABLE:
            raise ValueError(f'账户 {account.name} 不是应收类型')
        return account.current_balance_minor

    def get_receivable_transactions(
        self,
        session: Session,
        account_id: str | None = None,
        *,
        type_filter: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Transaction]:
        """查询应收相关流水。

        Args:
            session: 活动会话。
            account_id: 可选，按应收账户筛选。
            type_filter: 可选，按类型筛选 (receivable_advance/receivable_repayment).
            date_from: 可选，开始日期。
            date_to: 可选，结束日期。

        Returns:
            Transaction 列表，按日期降序。
        """
        q = select(Transaction).where(
            Transaction.type.in_([
                TransactionType.RECEIVABLE_ADVANCE,
                TransactionType.RECEIVABLE_REPAYMENT,
            ])
        )

        if account_id is not None:
            from sqlalchemy import or_
            q = q.where(
                or_(
                    Transaction.account_out_id == account_id,
                    Transaction.account_in_id == account_id,
                )
            )

        if type_filter is not None:
            q = q.where(Transaction.type == type_filter)

        if date_from is not None:
            q = q.where(Transaction.transaction_date >= date_from)

        if date_to is not None:
            q = q.where(Transaction.transaction_date <= date_to)

        q = q.order_by(
            Transaction.transaction_date.desc(),
            Transaction.created_at.desc(),
            Transaction.id.desc(),
        )

        return list(session.scalars(q))

    def get_pending_receivables(
        self, session: Session
    ) -> list[ReceivableSummary]:
        """获取所有仍有未收余额的债务人汇总。

        Returns:
            按余额降序排列的汇总列表。
        """
        accounts = self.get_receivable_accounts(session)
        results: list[ReceivableSummary] = []

        for acct in accounts:
            if acct.current_balance_minor <= 0:
                continue

            # 统计笔数
            pending_count = session.scalar(
                select(func.count(Transaction.id))
                .where(Transaction.account_in_id == acct.id)
                .where(Transaction.type == TransactionType.RECEIVABLE_ADVANCE)
            ) or 0

            # 累计垫付
            total_advanced = session.scalar(
                select(func.coalesce(func.sum(Transaction.amount_minor), 0))
                .where(Transaction.account_in_id == acct.id)
                .where(Transaction.type == TransactionType.RECEIVABLE_ADVANCE)
            ) or 0

            # 累计还款
            total_repaid = session.scalar(
                select(func.coalesce(func.sum(Transaction.amount_minor), 0))
                .where(Transaction.account_out_id == acct.id)
                .where(Transaction.type == TransactionType.RECEIVABLE_REPAYMENT)
            ) or 0

            results.append(ReceivableSummary(
                account_id=acct.id,
                account_name=acct.name,
                balance_minor=acct.current_balance_minor,
                pending_count=pending_count,
                total_advanced_minor=total_advanced,
                total_repaid_minor=total_repaid,
            ))

        results.sort(key=lambda r: r.balance_minor, reverse=True)
        return results

    def get_all_receivable_summaries(
        self, session: Session
    ) -> list[ReceivableSummary]:
        """获取所有 receivable 账户的汇总（含已结清的）。"""
        accounts = self.get_receivable_accounts(session)
        results: list[ReceivableSummary] = []

        for acct in accounts:
            pending_count = session.scalar(
                select(func.count(Transaction.id))
                .where(Transaction.account_in_id == acct.id)
                .where(Transaction.type == TransactionType.RECEIVABLE_ADVANCE)
            ) or 0

            total_advanced = session.scalar(
                select(func.coalesce(func.sum(Transaction.amount_minor), 0))
                .where(Transaction.account_in_id == acct.id)
                .where(Transaction.type == TransactionType.RECEIVABLE_ADVANCE)
            ) or 0

            total_repaid = session.scalar(
                select(func.coalesce(func.sum(Transaction.amount_minor), 0))
                .where(Transaction.account_out_id == acct.id)
                .where(Transaction.type == TransactionType.RECEIVABLE_REPAYMENT)
            ) or 0

            results.append(ReceivableSummary(
                account_id=acct.id,
                account_name=acct.name,
                balance_minor=acct.current_balance_minor,
                pending_count=pending_count,
                total_advanced_minor=total_advanced,
                total_repaid_minor=total_repaid,
            ))

        results.sort(key=lambda r: r.balance_minor, reverse=True)
        return results

    def build_transaction_views(
        self,
        session: Session,
        transactions: list[Transaction],
    ) -> list[ReceivableTransactionView]:
        """将 Transaction 列表转为 UI 视图对象。"""
        accounts_map = {
            a.id: a for a in session.scalars(select(Account))
        }

        views: list[ReceivableTransactionView] = []
        for tx in transactions:
            if tx.type == TransactionType.RECEIVABLE_ADVANCE:
                # advance: out=funding, in=debtor(receivable)
                debtor_id = tx.account_in_id
                counter_id = tx.account_out_id
            else:
                # repayment: out=debtor(receivable), in=collection
                debtor_id = tx.account_out_id
                counter_id = tx.account_in_id

            debtor_name = accounts_map.get(debtor_id)
            debtor_name = debtor_name.name if debtor_name else '未知'
            counter_name = accounts_map.get(counter_id) if counter_id else None
            counter_name = counter_name.name if counter_name else '未知'

            views.append(ReceivableTransactionView(
                transaction_id=tx.id,
                transaction_type=tx.type,
                transaction_date=tx.transaction_date,
                debtor_account_id=debtor_id or '',
                debtor_account_name=debtor_name,
                counter_account_id=counter_id,
                counter_account_name=counter_name,
                amount_minor=tx.amount_minor,
                note=tx.note,
            ))

        return views

    def get_non_receivable_asset_accounts(
        self, session: Session
    ) -> list[Account]:
        """获取可用于垫付/还款的非应收资产账户（现金/银行卡）。"""
        return list(
            session.scalars(
                select(Account)
                .where(Account.type.in_([
                    AccountType.CASH,
                    AccountType.BANK,
                ]))
                .where(Account.is_enabled)
                .where(Account.is_editable)
                .order_by(Account.name)
            )
        )

    # ═══════════════════════════════════════════════════
    #  验证
    # ═══════════════════════════════════════════════════

    def _validate_debtor(
        self, session: Session, account_id: str
    ) -> Account:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'债务人账户不存在: {account_id}')
        if account.type != AccountType.RECEIVABLE:
            raise ValueError(
                f'账户 "{account.name}" 类型为 {account.type}，不是应收账户'
            )
        if not account.is_enabled:
            raise ValueError(f'应收账户 "{account.name}" 已停用')
        if not account.is_editable:
            raise ValueError(f'应收账户 "{account.name}" 不可编辑')
        return account

    def _validate_funding_source(
        self, session: Session, account_id: str
    ) -> Account:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'资金来源账户不存在: {account_id}')
        if account.type == AccountType.RECEIVABLE:
            raise ValueError(
                f'资金来源账户 "{account.name}" 不能是应收类型，'
                f'请选择现金或银行账户'
            )
        if not account.is_enabled:
            raise ValueError(f'资金来源账户 "{account.name}" 已停用')
        return account

    def _validate_collection_target(
        self, session: Session, account_id: str
    ) -> Account:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'收款账户不存在: {account_id}')
        if account.type == AccountType.RECEIVABLE:
            raise ValueError(
                f'收款账户 "{account.name}" 不能是应收类型，'
                f'请选择现金或银行账户'
            )
        if not account.is_enabled:
            raise ValueError(f'收款账户 "{account.name}" 已停用')
        return account
