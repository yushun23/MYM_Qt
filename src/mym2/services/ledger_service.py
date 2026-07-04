"""账本服务 — 唯一写账入口。

所有会改变 transactions 表及 accounts.current_balance_minor 的操作
都必须经过本服务。UI、导入器、AI 模块不得直写数据库。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.audit_event import AuditEvent
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import (
    AuditAction,
    TransactionType,
)
from mym2.domain.money import validate_positive_amount_minor
from mym2.services.balance_service import BalanceService
from mym2.services.dto import CreateTransactionDTO, UpdateTransactionDTO
from mym2.services.validators import (
    validate_account_for_transaction_type,
    validate_account_not_receivable,
    validate_account_writable,
    validate_category_compatible,
    validate_transaction_editable,
)

logger = logging.getLogger('mym2.services.ledger_service')


class LedgerService:
    """唯一写账入口。

    每个公开方法接收一个已开启事务的 Session；
    调用方负责 commit/rollback。
    """

    def __init__(self, balance_service: BalanceService | None = None) -> None:
        self._balance = balance_service or BalanceService()

    # ═══════════════════════════════════════════════════
    #  创建流水
    # ═══════════════════════════════════════════════════

    def create_transaction(
        self, session: Session, dto: CreateTransactionDTO
    ) -> Transaction:
        """创建一笔流水。

        验证参数、账户、分类，创建流水，重算受影响账户余额，
        写入审计事件。

        Args:
            session: 活动会话（需在事务中）。
            dto: 创建流水的 DTO。

        Returns:
            已持久化的 Transaction 实例。

        Raises:
            ValueError: 验证失败。
        """
        # 1. 验证金额
        validate_positive_amount_minor(dto.amount_minor)

        # 2. 加载并验证账户
        _ = self._get_and_validate_out_account(session, dto)
        _ = self._get_and_validate_in_account(session, dto)

        # 3. 加载并验证分类
        category = self._get_and_validate_category(session, dto)

        # 4. 创建流水
        now = datetime.now(UTC).replace(tzinfo=None)
        tx = Transaction(
            id=None,  # 由 UUIDMixin 自动生成
            transaction_date=dto.transaction_date,
            type=dto.transaction_type.value,
            category_id=category.id if category else None,
            account_out_id=dto.account_out_id,
            account_in_id=dto.account_in_id,
            amount_minor=dto.amount_minor,
            note=dto.note,
            source=dto.source,
            is_cleared=False,
            is_locked=False,
            created_at=now,
            updated_at=now,
        )
        session.add(tx)
        session.flush([tx])

        # 5. 重算受影响账户余额
        affected = self._collect_affected_accounts(dto)
        self._balance.recalculate_accounts(session, affected)

        # 6. 审计
        self._record_audit(
            session,
            action=AuditAction.CREATE,
            entity_type='transaction',
            entity_id=tx.id,
            changes_json=self._serialize_create(tx),
        )

        logger.info('创建流水 %s [%s] %d 分', tx.id, tx.type, tx.amount_minor)
        return tx

    # ═══════════════════════════════════════════════════
    #  编辑流水
    # ═══════════════════════════════════════════════════

    def update_transaction(
        self,
        session: Session,
        transaction_id: str,
        dto: UpdateTransactionDTO,
    ) -> Transaction:
        """编辑一笔流水。

        仅修改 dto 中非 None 的字段。
        如果修改了账户或金额，重算所有受影响账户余额。

        Args:
            session: 活动会话。
            transaction_id: 要编辑的流水 ID。
            dto: 更新 DTO。

        Returns:
            更新后的 Transaction。

        Raises:
            ValueError: 流水不存在、被锁定或验证失败。
        """
        tx = session.get(Transaction, transaction_id)
        if tx is None:
            raise ValueError(f'流水不存在: {transaction_id}')

        validate_transaction_editable(tx)

        # 记录旧状态
        old_snapshot = self._serialize_transaction(tx)
        old_affected = self._collect_transaction_accounts(tx)

        # 受影响账户由事务流水决定

        # 应用编辑
        if dto.transaction_date is not None:
            tx.transaction_date = dto.transaction_date
        if dto.amount_minor is not None:
            validate_positive_amount_minor(dto.amount_minor)
            tx.amount_minor = dto.amount_minor

        # 编辑不改变 account_out_id（类型决定）；
        # account_in_id 仅对 transfer 且仅当提供时允许修改
        if dto.account_in_id is not None:
            if tx.type in (TransactionType.TRANSFER,):
                if tx.account_out_id == dto.account_in_id:
                    raise ValueError('转账的两个账户不能相同')
                # 验证新 target 账户
                in_account = session.get(Account, dto.account_in_id)
                if in_account is None:
                    raise ValueError(f'账户不存在: {dto.account_in_id}')
                validate_account_writable(in_account)
                validate_account_not_receivable(in_account)
                tx.account_in_id = dto.account_in_id
            else:
                raise ValueError(f'{tx.type} 类型不支持修改 account_in_id')

        if dto.category_id is not None:
            cat = session.get(Category, dto.category_id)
            if cat is None:
                raise ValueError(f'分类不存在: {dto.category_id}')
            validate_category_compatible(cat, TransactionType(tx.type))
            tx.category_id = dto.category_id

        if dto.note is not None:
            tx.note = dto.note

        tx.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush([tx])

        # 重算受影响账户余额
        new_affected = self._collect_transaction_accounts(tx)
        all_affected = list(set(old_affected + new_affected))
        self._balance.recalculate_accounts(session, all_affected)

        # 审计
        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type='transaction',
            entity_id=tx.id,
            changes_json=json.dumps({
                'old': old_snapshot,
                'new': self._serialize_transaction(tx),
            }, ensure_ascii=False, default=str),
        )

        logger.info('编辑流水 %s', tx.id)
        return tx

    # ═══════════════════════════════════════════════════
    #  删除流水
    # ═══════════════════════════════════════════════════

    def delete_transaction(
        self, session: Session, transaction_id: str
    ) -> None:
        """删除一笔流水。

        Args:
            session: 活动会话。
            transaction_id: 要删除的流水 ID。

        Raises:
            ValueError: 流水不存在、被锁定或为历史结算。
        """
        tx = session.get(Transaction, transaction_id)
        if tx is None:
            raise ValueError(f'流水不存在: {transaction_id}')

        validate_transaction_editable(tx)

        old_snapshot = self._serialize_transaction(tx)
        affected = self._collect_transaction_accounts(tx)

        # 删除
        session.delete(tx)
        session.flush()

        # 重算余额
        self._balance.recalculate_accounts(session, affected)

        # 审计
        self._record_audit(
            session,
            action=AuditAction.DELETE,
            entity_type='transaction',
            entity_id=transaction_id,
            changes_json=json.dumps(
                {'deleted': old_snapshot}, ensure_ascii=False, default=str
            ),
        )

        logger.info('删除流水 %s', transaction_id)

    # ═══════════════════════════════════════════════════
    #  内部辅助方法
    # ═══════════════════════════════════════════════════

    def _get_and_validate_out_account(
        self, session: Session, dto: CreateTransactionDTO
    ) -> Account:
        account = session.get(Account, dto.account_out_id)
        if account is None:
            raise ValueError(f'账户不存在: {dto.account_out_id}')
        validate_account_writable(account)
        validate_account_for_transaction_type(
            account, dto.transaction_type, role='out'
        )
        return account

    def _get_and_validate_in_account(
        self, session: Session, dto: CreateTransactionDTO
    ) -> Account | None:
        if dto.account_in_id is None:
            return None
        account = session.get(Account, dto.account_in_id)
        if account is None:
            raise ValueError(f'账户不存在: {dto.account_in_id}')
        validate_account_writable(account)
        validate_account_for_transaction_type(
            account, dto.transaction_type, role='in'
        )
        return account

    def _get_and_validate_category(
        self, session: Session, dto: CreateTransactionDTO
    ) -> Category | None:
        category = None
        if dto.category_id is not None:
            category = session.get(Category, dto.category_id)
            if category is None:
                raise ValueError(f'分类不存在: {dto.category_id}')
        validate_category_compatible(category, dto.transaction_type)
        return category

    @staticmethod
    def _collect_affected_accounts(dto: CreateTransactionDTO) -> list[str]:
        ids = [dto.account_out_id]
        if dto.account_in_id:
            ids.append(dto.account_in_id)
        return ids

    @staticmethod
    def _collect_transaction_accounts(tx: Transaction) -> list[str]:
        ids = [tx.account_out_id]
        if tx.account_in_id:
            ids.append(tx.account_in_id)
        return ids

    @staticmethod
    def _record_audit(
        session: Session,
        action: AuditAction,
        entity_type: str,
        entity_id: str,
        changes_json: str | None = None,
    ) -> None:
        event = AuditEvent(
            id=None,
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            changes_json=changes_json,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(event)
        session.flush()

    @staticmethod
    def _serialize_create(tx: Transaction) -> str:
        return json.dumps(
            LedgerService._serialize_transaction(tx),
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _serialize_transaction(tx: Transaction) -> dict:
        return {
            'id': tx.id,
            'type': tx.type,
            'transaction_date': str(tx.transaction_date),
            'account_out_id': tx.account_out_id,
            'account_in_id': tx.account_in_id,
            'category_id': tx.category_id,
            'amount_minor': tx.amount_minor,
            'note': tx.note,
            'source': tx.source,
            'is_locked': tx.is_locked,
        }
