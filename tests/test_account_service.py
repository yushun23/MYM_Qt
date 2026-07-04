"""账户服务测试。"""

import pytest
from sqlalchemy import func, select

from mym2.db.models.audit_event import AuditEvent
from mym2.domain.enums import AuditAction
from mym2.services.account_service import AccountService
from mym2.services.dto import CreateAccountDTO, UpdateAccountDTO


@pytest.fixture
def service():
    return AccountService()


# ── 创建账户 ──────────────────────────────────────

def test_create_cash_account(session, service):
    dto = CreateAccountDTO(
        name="现金钱包", type="cash", opening_balance_minor=100000
    )
    account = service.create_account(session, dto)
    session.commit()

    assert account.name == "现金钱包"
    assert account.type == "cash"
    assert account.opening_balance_minor == 100000
    assert account.current_balance_minor == 100000
    assert account.is_enabled is True
    assert account.is_editable is True
    assert account.is_locked is False
    assert account.currency == "CNY"


def test_create_credit_card_account(session, service):
    dto = CreateAccountDTO(
        name="招行信用卡", type="credit_card", group="信用"
    )
    account = service.create_account(session, dto)
    session.commit()

    assert account.type == "credit_card"
    assert account.group == "信用"
    assert account.is_locked is False


def test_create_investment_snapshot_locked(session, service):
    dto = CreateAccountDTO(
        name="旧投资账户", type="investment_snapshot"
    )
    account = service.create_account(session, dto)
    session.commit()

    assert account.is_locked is True
    assert account.is_editable is False


def test_create_duplicate_name_rejected(session, service):
    dto1 = CreateAccountDTO(name="测试账户", type="cash")
    service.create_account(session, dto1)
    session.commit()

    dto2 = CreateAccountDTO(name="测试账户", type="bank")
    with pytest.raises(ValueError, match="已存在"):
        service.create_account(session, dto2)


def test_create_empty_name_rejected(service):
    with pytest.raises(ValueError, match="不能为空"):
        CreateAccountDTO(name="", type="cash")


def test_create_invalid_type_rejected(service):
    with pytest.raises(ValueError, match="无效的账户类型"):
        CreateAccountDTO(name="test", type="invalid_type")


def test_create_negative_balance_rejected(service):
    with pytest.raises(ValueError, match="不能为负数"):
        CreateAccountDTO(name="test", type="cash", opening_balance_minor=-100)


def test_create_audit_event(session, service):
    dto = CreateAccountDTO(name="审计测试", type="cash")
    account = service.create_account(session, dto)
    session.commit()

    events = session.scalars(
        select(AuditEvent).where(
            AuditEvent.entity_type == "account",
            AuditEvent.entity_id == account.id,
        )
    ).all()
    assert len(events) == 1
    assert events[0].action == AuditAction.CREATE


# ── 编辑账户 ──────────────────────────────────────

def test_update_account_name(session, service):
    dto = CreateAccountDTO(name="原名", type="cash")
    account = service.create_account(session, dto)
    session.commit()

    update = UpdateAccountDTO(name="新名")
    updated = service.update_account(session, account.id, update)
    session.commit()

    assert updated.name == "新名"


def test_update_opening_balance_adjusts_current(session, service):
    dto = CreateAccountDTO(name="余额测试", type="cash", opening_balance_minor=50000)
    account = service.create_account(session, dto)
    session.commit()
    assert account.current_balance_minor == 50000

    update = UpdateAccountDTO(opening_balance_minor=100000)
    updated = service.update_account(session, account.id, update)
    session.commit()

    assert updated.opening_balance_minor == 100000
    assert updated.current_balance_minor == 100000  # 增加了 50000


def test_update_locked_account_rejected(session, service):
    dto = CreateAccountDTO(name="锁定账户", type="investment_snapshot")
    account = service.create_account(session, dto)
    session.commit()

    update = UpdateAccountDTO(name="改名")
    with pytest.raises(ValueError, match="已锁定"):
        service.update_account(session, account.id, update)


def test_update_nonexistent_account(session, service):
    with pytest.raises(ValueError, match="不存在"):
        service.update_account(session, "nonexistent-id", UpdateAccountDTO(name="x"))


def test_update_duplicate_name_rejected(session, service):
    dto1 = CreateAccountDTO(name="账户A", type="cash")
    dto2 = CreateAccountDTO(name="账户B", type="bank")
    service.create_account(session, dto1)
    a2 = service.create_account(session, dto2)
    session.commit()

    with pytest.raises(ValueError, match="已被其他账户使用"):
        service.update_account(session, a2.id, UpdateAccountDTO(name="账户A"))


# ── 启停账户 ──────────────────────────────────────

def test_disable_account(session, service):
    dto = CreateAccountDTO(name="待停用", type="cash")
    account = service.create_account(session, dto)
    session.commit()

    result = service.disable_account(session, account.id)
    session.commit()

    assert result.is_enabled is False


def test_disable_locked_account_rejected(session, service):
    dto = CreateAccountDTO(name="锁定", type="investment_snapshot")
    account = service.create_account(session, dto)
    session.commit()

    with pytest.raises(ValueError, match="已锁定"):
        service.disable_account(session, account.id)


def test_enable_account(session, service):
    dto = CreateAccountDTO(name="待启用", type="cash")
    account = service.create_account(session, dto)
    service.disable_account(session, account.id)
    session.commit()

    result = service.enable_account(session, account.id)
    session.commit()

    assert result.is_enabled is True


def test_enable_nonexistent_rejected(session, service):
    with pytest.raises(ValueError, match="不存在"):
        service.enable_account(session, "nonexistent-id")


def test_toggle_audit_event(session, service):
    dto = CreateAccountDTO(name="启停审计", type="cash")
    account = service.create_account(session, dto)
    session.commit()

    initial_count = session.scalar(
        select(func.count(AuditEvent.id))
    )

    service.disable_account(session, account.id)
    session.commit()

    new_count = session.scalar(
        select(func.count(AuditEvent.id))
    )
    assert new_count > initial_count


def test_dto_name_too_long_rejected():
    with pytest.raises(ValueError, match="不能超过"):
        CreateAccountDTO(name="x" * 101, type="cash")


def test_update_dto_name_too_long_rejected():
    with pytest.raises(ValueError, match="不能超过"):
        UpdateAccountDTO(name="x" * 101)


def test_update_dto_negative_balance_rejected():
    with pytest.raises(ValueError, match="不能为负数"):
        UpdateAccountDTO(opening_balance_minor=-100)


def test_update_dto_invalid_type_rejected():
    with pytest.raises(ValueError, match="无效的账户类型"):
        UpdateAccountDTO(type="invalid")


def test_receivable_account(session, service):
    dto = CreateAccountDTO(name="应收张三", type="receivable")
    account = service.create_account(session, dto)
    session.commit()
    assert account.type == "receivable"
    assert account.is_editable is True
    assert account.is_locked is False
