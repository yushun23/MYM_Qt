"""分类服务 — 分类 CRUD 的唯一写入口。

所有会改变 categories 表的操作都必须经过本服务。
UI 层不得直接操作 Category 模型。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym2.db.models.audit_event import AuditEvent
from mym2.db.models.category import Category
from mym2.domain.enums import AuditAction
from mym2.services.dto import CreateCategoryDTO, UpdateCategoryDTO

logger = logging.getLogger("mym2.services.category_service")


class CategoryService:
    """分类写服务。

    每个公开方法接收一个已开启事务的 Session；
    调用方负责 commit/rollback。
    """

    # ═══════════════════════════════════════════════════
    #  创建分类
    # ═══════════════════════════════════════════════════

    def create_category(
        self, session: Session, dto: CreateCategoryDTO
    ) -> Category:
        """创建新分类。

        Args:
            session: 活动会话（需在事务中）。
            dto: 创建分类的 DTO。

        Returns:
            已持久化的 Category 实例。

        Raises:
            ValueError: 验证失败。
        """
        # 检查同名同类型分类
        existing = session.scalar(
            select(Category).where(
                Category.name == dto.name.strip(),
                Category.type == dto.type,
            )
        )
        if existing is not None:
            raise ValueError(
                f'分类 "{dto.name.strip()}"（{dto.type}）已存在'
            )

        # 验证父分类
        if dto.parent_id is not None:
            parent = session.get(Category, dto.parent_id)
            if parent is None:
                raise ValueError(f"父分类不存在: {dto.parent_id}")

        now = datetime.now(UTC).replace(tzinfo=None)
        category = Category(
            id=None,
            name=dto.name.strip(),
            type=dto.type,
            parent_id=dto.parent_id,
            color=dto.color,
            icon=dto.icon,
            is_enabled=True,
            sort_order=dto.sort_order,
            created_at=now,
            updated_at=now,
        )
        session.add(category)
        session.flush([category])

        self._record_audit(
            session,
            action=AuditAction.CREATE,
            entity_type="category",
            entity_id=category.id,
            changes_json=json.dumps(
                {"name": category.name, "type": category.type},
                ensure_ascii=False,
            ),
        )

        logger.info("创建分类 %s [%s]", category.name, category.type)
        return category

    # ═══════════════════════════════════════════════════
    #  编辑分类
    # ═══════════════════════════════════════════════════

    def update_category(
        self,
        session: Session,
        category_id: str,
        dto: UpdateCategoryDTO,
    ) -> Category:
        """编辑分类。

        仅修改 dto 中非 None 的字段。
        不允许将分类类型改为 system（除非本身就是 system）。

        Args:
            session: 活动会话。
            category_id: 要编辑的分类 ID。
            dto: 更新 DTO。

        Returns:
            更新后的 Category。

        Raises:
            ValueError: 分类不存在、为系统分类且尝试修改关键字段。
        """
        category = session.get(Category, category_id)
        if category is None:
            raise ValueError(f"分类不存在: {category_id}")

        old_snapshot = {
            "name": category.name,
            "type": category.type,
            "sort_order": category.sort_order,
            "is_enabled": category.is_enabled,
        }

        # 系统分类保护
        if category.type == "system" and (dto.name is not None or dto.type is not None):
            raise ValueError(f'系统分类 "{category.name}" 不允许修改名称或类型')

        changed = False

        if dto.name is not None:
            new_name = dto.name.strip()
            existing = session.scalar(
                select(Category).where(
                    Category.name == new_name,
                    Category.type == (dto.type if dto.type else category.type),
                    Category.id != category_id,
                )
            )
            if existing is not None:
                raise ValueError(f'分类名称 "{new_name}" 已被使用')
            category.name = new_name
            changed = True

        if dto.type is not None:
            category.type = dto.type
            changed = True

        if dto.parent_id is not None:
            # 防止循环引用
            if dto.parent_id == category_id:
                raise ValueError("分类不能将自己设为父分类")
            category.parent_id = dto.parent_id
            changed = True

        if dto.color is not None:
            category.color = dto.color if dto.color else None
            changed = True

        if dto.icon is not None:
            category.icon = dto.icon if dto.icon else None
            changed = True

        if dto.sort_order is not None:
            category.sort_order = dto.sort_order
            changed = True

        if dto.is_enabled is not None:
            category.is_enabled = dto.is_enabled
            changed = True

        if changed:
            category.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.flush([category])

            self._record_audit(
                session,
                action=AuditAction.UPDATE,
                entity_type="category",
                entity_id=category.id,
                changes_json=json.dumps(
                    {"old": old_snapshot, "new": self._snapshot(category)},
                    ensure_ascii=False,
                ),
            )

            logger.info("编辑分类 %s", category.name)

        return category

    # ═══════════════════════════════════════════════════
    #  停用/启用分类
    # ═══════════════════════════════════════════════════

    def disable_category(
        self, session: Session, category_id: str
    ) -> Category:
        """停用分类。

        Args:
            session: 活动会话。
            category_id: 分类 ID。

        Returns:
            停用后的 Category。

        Raises:
            ValueError: 分类不存在或为系统分类。
        """
        category = session.get(Category, category_id)
        if category is None:
            raise ValueError(f"分类不存在: {category_id}")

        if category.type == "system":
            raise ValueError(f'系统分类 "{category.name}" 不允许停用')

        category.is_enabled = False
        category.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush([category])

        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type="category",
            entity_id=category.id,
            changes_json=json.dumps(
                {"action": "disable", "name": category.name},
                ensure_ascii=False,
            ),
        )

        logger.info("停用分类 %s", category.name)
        return category

    def enable_category(
        self, session: Session, category_id: str
    ) -> Category:
        """重新启用已停用的分类。

        Args:
            session: 活动会话。
            category_id: 分类 ID。

        Returns:
            启用后的 Category。

        Raises:
            ValueError: 分类不存在。
        """
        category = session.get(Category, category_id)
        if category is None:
            raise ValueError(f"分类不存在: {category_id}")

        category.is_enabled = True
        category.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.flush([category])

        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type="category",
            entity_id=category.id,
            changes_json=json.dumps(
                {"action": "enable", "name": category.name},
                ensure_ascii=False,
            ),
        )

        logger.info("启用分类 %s", category.name)
        return category

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
    def _snapshot(category: Category) -> dict:
        return {
            "name": category.name,
            "type": category.type,
            "sort_order": category.sort_order,
            "is_enabled": category.is_enabled,
        }
