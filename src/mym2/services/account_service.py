"""账户服务 — 账户 CRUD 的唯一写入口。

所有会改变 accounts 表的操作都必须经过本服务。
UI 层不得直接操作 Account 模型。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.audit_event import AuditEvent
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType, AuditAction
from mym2.services.dto import CreateAccountDTO, UpdateAccountDTO

logger = logging.getLogger("mym2.services.account_service")


class AccountService:
    """账户写服务。

    每个公开方法接收一个已开启事务的 Session；
    调用方负责 commit/rollback。
    """

    # ═══════════════════════════════════════════════════
    #  创建账户
    # ═══════════════════════════════════════════════════

    def create_account(
        self, session: Session, dto: CreateAccountDTO
    ) -> Account:
        """创建新账户。

        Args:
            session: 活动会话（需在事务中）。
            dto: 创建账户的 DTO。

        Returns:
            已持久化的 Account 实例。

        Raises:
            ValueError: 验证失败。
        """
        # 检查同名账户
        existing = session.scalar(
            select(Account).where(Account.name == dto.name.strip())
        )
        if existing is not None:
            raise ValueError(f'账户名称 "{dto.name.strip()}" 已存在')

        now = datetime.now(UTC).replace(tzinfo=None)
        account = Account(
            id=None,
            name=dto.name.strip(),
            type=dto.type,
            group=dto.group,
            is_enabled=True,
            opening_balance_minor=dto.opening_balance_minor,
            current_balance_minor=dto.opening_balance_minor,
            is_locked=dto.type == AccountType.INVESTMENT_SNAPSHOT,
            is_editable=dto.type != AccountType.INVESTMENT_SNAPSHOT,
            currency=dto.currency,
            notes=dto.notes,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.flush([account])

        self._record_audit(
            session,
            action=AuditAction.CREATE,
            entity_type="account",
            entity_id=account.id,
            changes_json=json.dumps(
                {"name": account.name, "type": account.type},
                ensure_ascii=False,
            ),
        )

        logger.info("创建账户 %s [%s]", account.name, account.type)
        return account

    # ═══════════════════════════════════════════════════
    #  编辑账户
    # ═══════════════════════════════════════════════════

    def update_account(
        self,
        session: Session,
        account_id: str,
        dto: UpdateAccountDTO,
    ) -> Account:
        """编辑账户。

        仅修改 dto 中非 None 的字段。
        若修改了期初余额，同步调整 current_balance_minor。

        Args:
            session: 活动会话。
            account_id: 要编辑的账户 ID。
            dto: 更新 DTO。

        Returns:
            更新后的 Account。

        Raises:
            ValueError: 账户不存在、被锁定或验证失败。
        """
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"账户不存在: {account_id}")

        if account.is_locked:
            raise ValueError(f'账户 "{account.name}" 已锁定，无法编辑')

        if not account.is_editable:
            raise ValueError(f'账户 "{account.name}" 为历史投资快照，不可编辑')

        old_snapshot = {
            "name": account.name,
            "type": account.type,
            "group": account.group,
            "opening_balance_minor": account.opening_balance_minor,
        }

        changed = False

        if dto.name is not None:
            new_name = dto.name.strip()
            existing = session.scalar(
                select(Account).where(
                    Account.name == new_name, Account.id != account_id
                )
            )
            if existing is not None:
                raise ValueError(f'账户名称 "{new_name}" 已被其他账户使用')
            account.name = new_name
            changed = True

        if dto.type is not None:
            account.type = dto.type
            changed = True

        if dto.group is not None:
            account.group = dto.group if dto.group else None
            changed = True

        if dto.opening_balance_minor is not None:
            delta = dto.opening_balance_minor - account.opening_balance_minor
            account.opening_balance_minor = dto.opening_balance_minor
            account.current_balance_minor += delta
            changed = True

        if dto.currency is not None:
            account.currency = dto.currency
            changed = True

        if dto.notes is not None:
            account.notes = dto.notes if dto.notes else None
            changed = True

        if dto.is_enabled is not None:
            if not dto.is_enabled:
                # 停用前检查是否有流水
                tx_count = session.scalar(
                    select(func.count(Transaction.id)).where(
                        (Transaction.account_out_id == account_id)
                        | (Transaction.account_in_id == account_id)
                    )
                ) or 0
                if tx_count > 0 and not account.is_enabled:
                    # 从启用到停用，允许但有提示
                    pass
            account.is_enabled = dto.is_enabled
            changed = True

        if changed:
            account.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.flush([account])

            self._record_audit(
                session,
                action=AuditAction.UPDATE,
                entity_type="account",
                entity_id=account.id,
                changes_json=json.dumps(
                    {"old": old_snapshot, "new": self._snapshot(account)},
                    ensure_ascii=False,
                ),
            )

            logger.info("编辑账户 %s", account.name)

        return account

    # ═══════════════════════════════════════════════════
    #  停用账户
    # ═══════════════════════════════════════════════════

    def disable_account(self, session: Session, account_id: str) -> Account:
        """停用账户（有流水的账户禁止物理删除）。

        Args:
            session: 活动会话。
            account_id: 账户 ID。

        Returns:
            停用后的 Account。

        Raises:
            ValueError: 账户不存在或已被锁定。
        """
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"账户不存在: {account_id}")

        if account.is_locked:
            raise ValueError(f'账户 "{account.name}" 已锁定，无法停用')

        account.is_enabled = False
        account.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush([account])

        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type="account",
            entity_id=account.id,
            changes_json=json.dumps(
                {"action": "disable", "name": account.name},
                ensure_ascii=False,
            ),
        )

        logger.info("停用账户 %s", account.name)
        return account

    # ═══════════════════════════════════════════════════
    #  启用账户
    # ═══════════════════════════════════════════════════

    def enable_account(self, session: Session, account_id: str) -> Account:
        """重新启用已停用的账户。

        Args:
            session: 活动会话。
            account_id: 账户 ID。

        Returns:
            启用后的 Account。

        Raises:
            ValueError: 账户不存在。
        """
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"账户不存在: {account_id}")

        account.is_enabled = True
        account.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush([account])

        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type="account",
            entity_id=account.id,
            changes_json=json.dumps(
                {"action": "enable", "name": account.name},
                ensure_ascii=False,
            ),
        )

        logger.info("启用账户 %s", account.name)
        return account

    # ═══════════════════════════════════════════════════
    #  辅助
    # ═══════════════════════════════════════════════════

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
    def _snapshot(account: Account) -> dict:
        return {
            "name": account.name,
            "type": account.type,
            "group": account.group,
            "opening_balance_minor": account.opening_balance_minor,
            "is_enabled": account.is_enabled,
            "currency": account.currency,
        }
