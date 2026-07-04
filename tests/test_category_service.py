"""分类服务测试。"""

import pytest
from sqlalchemy import select

from mym2.db.models.audit_event import AuditEvent
from mym2.services.category_service import CategoryService
from mym2.services.dto import CreateCategoryDTO, UpdateCategoryDTO


@pytest.fixture
def service():
    return CategoryService()


# ── 创建分类 ──────────────────────────────────────

def test_create_expense_category(session, service):
    dto = CreateCategoryDTO(name="餐饮", type="expense", sort_order=1)
    cat = service.create_category(session, dto)
    session.commit()

    assert cat.name == "餐饮"
    assert cat.type == "expense"
    assert cat.sort_order == 1
    assert cat.is_enabled is True


def test_create_income_category(session, service):
    dto = CreateCategoryDTO(name="工资", type="income", color="#00FF00")
    cat = service.create_category(session, dto)
    session.commit()

    assert cat.type == "income"
    assert cat.color == "#00FF00"


def test_create_with_parent(session, service):
    parent = service.create_category(
        session, CreateCategoryDTO(name="食品", type="expense")
    )
    session.commit()

    child = service.create_category(
        session,
        CreateCategoryDTO(name="水果", type="expense", parent_id=parent.id),
    )
    session.commit()

    assert child.parent_id == parent.id


def test_create_duplicate_name_type_rejected(session, service):
    dto1 = CreateCategoryDTO(name="餐饮", type="expense")
    service.create_category(session, dto1)
    session.commit()

    dto2 = CreateCategoryDTO(name="餐饮", type="expense")
    with pytest.raises(ValueError, match="已存在"):
        service.create_category(session, dto2)


def test_create_same_name_different_type_allowed(session, service):
    dto1 = CreateCategoryDTO(name="餐饮", type="expense")
    service.create_category(session, dto1)
    session.commit()

    dto2 = CreateCategoryDTO(name="餐饮", type="income")
    cat2 = service.create_category(session, dto2)
    session.commit()
    assert cat2 is not None


def test_create_invalid_type_rejected(service):
    with pytest.raises(ValueError, match="无效的分类类型"):
        CreateCategoryDTO(name="test", type="invalid")


def test_create_empty_name_rejected(service):
    with pytest.raises(ValueError, match="不能为空"):
        CreateCategoryDTO(name="", type="expense")


def test_create_audit_event(session, service):
    dto = CreateCategoryDTO(name="测试", type="expense")
    cat = service.create_category(session, dto)
    session.commit()

    events = session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type == "category",
            AuditEvent.entity_id == cat.id,
        )
    ).all()
    assert len(events) == 1


# ── 编辑分类 ──────────────────────────────────────

def test_update_category_name(session, service):
    dto = CreateCategoryDTO(name="旧名", type="expense")
    cat = service.create_category(session, dto)
    session.commit()

    updated = service.update_category(session, cat.id, UpdateCategoryDTO(name="新名"))
    session.commit()

    assert updated.name == "新名"


def test_update_sort_order(session, service):
    dto = CreateCategoryDTO(name="排序测试", type="expense", sort_order=5)
    cat = service.create_category(session, dto)
    session.commit()

    updated = service.update_category(
        session, cat.id, UpdateCategoryDTO(sort_order=10)
    )
    session.commit()

    assert updated.sort_order == 10


def test_update_system_category_rejected(session, service):
    dto = CreateCategoryDTO(name="系统分类", type="system")
    cat = service.create_category(session, dto)
    session.commit()

    with pytest.raises(ValueError, match="系统分类"):
        service.update_category(session, cat.id, UpdateCategoryDTO(name="改名"))


def test_update_self_parent_rejected(session, service):
    dto = CreateCategoryDTO(name="自引用", type="expense")
    cat = service.create_category(session, dto)
    session.commit()

    with pytest.raises(ValueError, match="不能将自己"):
        service.update_category(
            session, cat.id, UpdateCategoryDTO(parent_id=cat.id)
        )


def test_update_nonexistent_category(session, service):
    with pytest.raises(ValueError, match="不存在"):
        service.update_category(session, "bad-id", UpdateCategoryDTO(name="x"))


# ── 启停分类 ──────────────────────────────────────

def test_disable_category(session, service):
    dto = CreateCategoryDTO(name="待停用", type="expense")
    cat = service.create_category(session, dto)
    session.commit()

    result = service.disable_category(session, cat.id)
    session.commit()
    assert result.is_enabled is False


def test_disable_system_category_rejected(session, service):
    dto = CreateCategoryDTO(name="系统", type="system")
    cat = service.create_category(session, dto)
    session.commit()

    with pytest.raises(ValueError, match="系统分类"):
        service.disable_category(session, cat.id)


def test_enable_category(session, service):
    dto = CreateCategoryDTO(name="待启用", type="expense")
    cat = service.create_category(session, dto)
    service.disable_category(session, cat.id)
    session.commit()

    result = service.enable_category(session, cat.id)
    session.commit()
    assert result.is_enabled is True
