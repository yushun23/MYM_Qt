"""预算服务 — 预算模块的唯一写入口。

所有会改变 budget_periods / budget_lines 表的操作都必须经过本服务。
UI 层不得直接操作 BudgetPeriod / BudgetLine 模型。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from mym2.db.models.audit_event import AuditEvent
from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.domain.enums import AuditAction
from mym2.repositories.budget_repo import BudgetRepository
from mym2.services.dto import (
    BudgetLineDTO,
    CopyBudgetDTO,
    CreateBudgetPeriodDTO,
    UpdateBudgetLineDTO,
)

logger = logging.getLogger('mym2.services.budget_service')


class BudgetService:
    """预算写服务。

    每个公开方法接收一个已开启事务的 Session；
    调用方负责 commit/rollback。
    """

    def __init__(self) -> None:
        pass

    # ═══════════════════════════════════════════════════
    #  创建预算期间
    # ═══════════════════════════════════════════════════

    def create_period(
        self, session: Session, dto: CreateBudgetPeriodDTO
    ) -> BudgetPeriod:
        """创建新的预算期间及明细行。

        Args:
            session: 活动会话。
            dto: 创建预算期间的 DTO。

        Returns:
            已持久化的 BudgetPeriod 实例。

        Raises:
            ValueError: 期间已存在或验证失败。
        """
        # 检查是否已存在
        repo = BudgetRepository(session)
        existing = repo.get_period(dto.year, dto.month)
        if existing is not None:
            raise ValueError(
                f'{dto.year}年{dto.month}月的预算期间已存在'
            )

        # 验证所有分类存在
        category_ids = {line.category_id for line in dto.lines}
        for cid in category_ids:
            cat = session.get(Category, cid)
            if cat is None:
                raise ValueError(f'分类不存在: {cid}')

        # 创建期间
        period = BudgetPeriod(
            id=None,
            year=dto.year,
            month=dto.month,
            is_closed=False,
        )
        session.add(period)
        session.flush([period])

        # 创建明细行
        for line_dto in dto.lines:
            bl = BudgetLine(
                id=None,
                budget_period_id=period.id,
                category_id=line_dto.category_id,
                type=line_dto.type,
                amount_minor=line_dto.amount_minor,
                threshold_minor=line_dto.threshold_minor,
                group=line_dto.group,
                sort_order=line_dto.sort_order,
                note=line_dto.note,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(bl)

        session.flush()

        self._record_audit(
            session,
            action=AuditAction.CREATE,
            entity_type='budget_period',
            entity_id=period.id,
            changes_json=json.dumps({
                'year': dto.year,
                'month': dto.month,
                'line_count': len(dto.lines),
            }, ensure_ascii=False),
        )

        logger.info(
            '创建预算期间 %d-%02d（%d 行）', dto.year, dto.month, len(dto.lines)
        )
        return period

    # ═══════════════════════════════════════════════════
    #  复制上月预算
    # ═══════════════════════════════════════════════════

    def copy_from_previous(
        self, session: Session, dto: CopyBudgetDTO
    ) -> BudgetPeriod:
        """从上一个有预算的月份复制预算明细。

        查找最近的已存在预算期间，复制其所有明细行。

        Args:
            session: 活动会话。
            dto: 目标年月。

        Returns:
            新创建的 BudgetPeriod 实例。

        Raises:
            ValueError: 目标期间已存在、无上月预算或验证失败。
        """
        repo = BudgetRepository(session)

        # 检查目标是否存在
        existing = repo.get_period(dto.year, dto.month)
        if existing is not None:
            raise ValueError(
                f'{dto.year}年{dto.month}月的预算期间已存在'
            )

        # 查找上一个有预算的月份
        source = repo.get_previous_period(dto.year, dto.month)
        if source is None:
            # 尝试查找任意最近期间
            all_periods = repo.list_periods(limit=1)
            source = all_periods[0] if all_periods else None

        if source is None:
            raise ValueError('没有可复制的前期预算')

        source_lines = repo.get_lines(source.id)
        if not source_lines:
            raise ValueError('前期预算无明细行可复制')

        # 创建新期间
        period = BudgetPeriod(
            id=None,
            year=dto.year,
            month=dto.month,
            is_closed=False,
        )
        session.add(period)
        session.flush([period])

        # 复制明细行
        for sl in source_lines:
            bl = BudgetLine(
                id=None,
                budget_period_id=period.id,
                category_id=sl.category_id,
                type=sl.type,
                amount_minor=sl.amount_minor,
                threshold_minor=sl.threshold_minor,
                group=sl.group,
                sort_order=sl.sort_order,
                note=sl.note,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(bl)

        session.flush()

        self._record_audit(
            session,
            action=AuditAction.CREATE,
            entity_type='budget_period',
            entity_id=period.id,
            changes_json=json.dumps({
                'year': dto.year,
                'month': dto.month,
                'copied_from': f'{source.year}-{source.month:02d}',
                'line_count': len(source_lines),
            }, ensure_ascii=False),
        )

        logger.info(
            '从 %d-%02d 复制预算到 %d-%02d（%d 行）',
            source.year, source.month, dto.year, dto.month, len(source_lines),
        )
        return period

    # ═══════════════════════════════════════════════════
    #  编辑预算明细行
    # ═══════════════════════════════════════════════════

    def update_line(
        self,
        session: Session,
        line_id: str,
        dto: UpdateBudgetLineDTO,
    ) -> BudgetLine:
        """编辑预算明细行。

        如果期间已关闭则拒绝修改。

        Args:
            session: 活动会话。
            line_id: 明细行 ID。
            dto: 更新 DTO。

        Returns:
            更新后的 BudgetLine。

        Raises:
            ValueError: 行不存在、期间已关闭或验证失败。
        """
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError(f'预算明细不存在: {line_id}')

        period = session.get(BudgetPeriod, line.budget_period_id)
        if period is not None and period.is_closed:
            raise ValueError(
                f'{period.year}年{period.month}月预算已关闭，不可编辑'
            )

        old_snapshot = self._snapshot_line(line)
        changed = False

        if dto.category_id is not None:
            cat = session.get(Category, dto.category_id)
            if cat is None:
                raise ValueError(f'分类不存在: {dto.category_id}')
            line.category_id = dto.category_id
            changed = True

        if dto.type is not None:
            line.type = dto.type
            changed = True

        if dto.amount_minor is not None:
            line.amount_minor = dto.amount_minor
            changed = True

        if dto.group is not None:
            line.group = dto.group if dto.group else None
            changed = True

        if dto.threshold_minor is not None:
            line.threshold_minor = dto.threshold_minor
            changed = True

        if dto.sort_order is not None:
            line.sort_order = dto.sort_order
            changed = True

        if dto.note is not None:
            line.note = dto.note if dto.note else None
            changed = True

        if changed:
            line.updated_at = datetime.now(UTC).replace(tzinfo=None)
            session.flush([line])

            self._record_audit(
                session,
                action=AuditAction.UPDATE,
                entity_type='budget_line',
                entity_id=line.id,
                changes_json=json.dumps({
                    'old': old_snapshot,
                    'new': self._snapshot_line(line),
                }, ensure_ascii=False),
            )

            logger.info('编辑预算明细 %s', line.id)

        return line

    # ═══════════════════════════════════════════════════
    #  删除预算明细行
    # ═══════════════════════════════════════════════════

    def delete_line(self, session: Session, line_id: str) -> None:
        """删除预算明细行。

        如果期间已关闭则拒绝删除。

        Args:
            session: 活动会话。
            line_id: 明细行 ID。

        Raises:
            ValueError: 行不存在或期间已关闭。
        """
        line = session.get(BudgetLine, line_id)
        if line is None:
            raise ValueError(f'预算明细不存在: {line_id}')

        period = session.get(BudgetPeriod, line.budget_period_id)
        if period is not None and period.is_closed:
            raise ValueError(
                f'{period.year}年{period.month}月预算已关闭，不可删除'
            )

        old_snapshot = self._snapshot_line(line)
        session.delete(line)
        session.flush()

        self._record_audit(
            session,
            action=AuditAction.DELETE,
            entity_type='budget_line',
            entity_id=line_id,
            changes_json=json.dumps(
                {'deleted': old_snapshot}, ensure_ascii=False
            ),
        )

        logger.info('删除预算明细 %s', line_id)

    # ═══════════════════════════════════════════════════
    #  添加预算明细行
    # ═══════════════════════════════════════════════════

    def add_line(
        self, session: Session, period_id: str, dto: BudgetLineDTO
    ) -> BudgetLine:
        """向已有预算期间添加明细行。

        Args:
            session: 活动会话。
            period_id: 预算期间 ID。
            dto: 预算明细 DTO。

        Returns:
            新创建的 BudgetLine。

        Raises:
            ValueError: 期间不存在、已关闭或验证失败。
        """
        period = session.get(BudgetPeriod, period_id)
        if period is None:
            raise ValueError(f'预算期间不存在: {period_id}')

        if period.is_closed:
            raise ValueError(
                f'{period.year}年{period.month}月预算已关闭，不可添加'
            )

        cat = session.get(Category, dto.category_id)
        if cat is None:
            raise ValueError(f'分类不存在: {dto.category_id}')

        line = BudgetLine(
            id=None,
            budget_period_id=period_id,
            category_id=dto.category_id,
            type=dto.type,
            amount_minor=dto.amount_minor,
            threshold_minor=dto.threshold_minor,
            group=dto.group,
            sort_order=dto.sort_order,
            note=dto.note,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(line)
        session.flush([line])

        self._record_audit(
            session,
            action=AuditAction.CREATE,
            entity_type='budget_line',
            entity_id=line.id,
            changes_json=json.dumps(
                self._snapshot_line(line), ensure_ascii=False
            ),
        )

        logger.info('添加预算明细 %s（%d-%02d）', line.id, period.year, period.month)
        return line

    # ═══════════════════════════════════════════════════
    #  关闭/重新打开预算期间
    # ═══════════════════════════════════════════════════

    def close_period(self, session: Session, period_id: str) -> BudgetPeriod:
        """关闭预算期间（禁止编辑）。

        Args:
            session: 活动会话。
            period_id: 预算期间 ID。

        Returns:
            关闭后的 BudgetPeriod。

        Raises:
            ValueError: 期间不存在。
        """
        period = session.get(BudgetPeriod, period_id)
        if period is None:
            raise ValueError(f'预算期间不存在: {period_id}')

        if period.is_closed:
            return period

        period.is_closed = True
        session.flush([period])

        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type='budget_period',
            entity_id=period.id,
            changes_json=json.dumps(
                {'action': 'close', 'year': period.year, 'month': period.month},
                ensure_ascii=False,
            ),
        )

        logger.info('关闭预算期间 %d-%02d', period.year, period.month)
        return period

    def reopen_period(self, session: Session, period_id: str) -> BudgetPeriod:
        """重新打开预算期间。

        Args:
            session: 活动会话。
            period_id: 预算期间 ID。

        Returns:
            重新打开后的 BudgetPeriod。

        Raises:
            ValueError: 期间不存在。
        """
        period = session.get(BudgetPeriod, period_id)
        if period is None:
            raise ValueError(f'预算期间不存在: {period_id}')

        if not period.is_closed:
            return period

        period.is_closed = False
        session.flush([period])

        self._record_audit(
            session,
            action=AuditAction.UPDATE,
            entity_type='budget_period',
            entity_id=period.id,
            changes_json=json.dumps(
                {'action': 'reopen', 'year': period.year, 'month': period.month},
                ensure_ascii=False,
            ),
        )

        logger.info('重新打开预算期间 %d-%02d', period.year, period.month)
        return period

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
    def _snapshot_line(line: BudgetLine) -> dict:
        return {
            'id': line.id,
            'category_id': line.category_id,
            'type': line.type,
            'amount_minor': line.amount_minor,
            'threshold_minor': line.threshold_minor,
            'group': line.group,
            'sort_order': line.sort_order,
            'note': line.note,
        }
