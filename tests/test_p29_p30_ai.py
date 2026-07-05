"""Tests for P29-P30 – AI chat sessions, messages, actions, and approval workflow."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.ai_service import (
    AIService,
    ActionProposal,
    ActionSpec,
)
from mym.domain.entities.ai_ import ChatMessage
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.enums import (
    AccountType,
    ActionRiskLevel,
    CategoryType,
)
from mym.infrastructure.database.db_manager import DatabaseManager


@pytest.fixture
def db_mgr():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    yield mgr
    mgr.close()
    tmp_path.unlink(missing_ok=True)


@pytest.fixture
def session(db_mgr: DatabaseManager) -> Session:
    s = db_mgr.new_session()
    yield s
    s.close()


class TestChatSessions:
    def test_create_session(self, session):
        svc = AIService(session)
        chat = svc.create_session()
        assert chat.id is not None
        assert chat.title == "新对话"

    def test_list_sessions(self, session):
        svc = AIService(session)
        svc.create_session(title="对话1")
        svc.create_session(title="对话2")
        session.flush()

        sessions = svc.list_sessions()
        assert len(sessions) == 2

    def test_delete_session(self, session):
        svc = AIService(session)
        chat = svc.create_session()
        session.flush()

        assert svc.delete_session(chat.id)
        session.flush()
        assert svc.get_session(chat.id) is None

    def test_clear_all_history(self, session):
        svc = AIService(session)
        svc.create_session()
        svc.create_session()
        session.flush()

        count = svc.clear_all_history()
        assert count == 2
        assert len(svc.list_sessions()) == 0


class TestChatMessages:
    def test_add_message(self, session):
        svc = AIService(session)
        chat = svc.create_session()
        session.flush()

        msg = svc.add_message(chat.id, "user", "你好")
        assert msg.role == "user"
        assert msg.content == "你好"

    def test_get_messages(self, session):
        svc = AIService(session)
        chat = svc.create_session()
        session.flush()

        svc.add_message(chat.id, "user", "问题1")
        svc.add_message(chat.id, "assistant", "回答1")
        svc.add_message(chat.id, "user", "问题2")
        session.flush()

        messages = svc.get_messages(chat.id)
        assert len(messages) == 3
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_action_status_update(self, session):
        svc = AIService(session)
        chat = svc.create_session()
        session.flush()

        msg = svc.add_message(chat.id, "assistant", "建议操作", has_action_proposal=True)
        msg.action_status = "pending"
        session.flush()

        svc.update_action_status(msg.id, "executed")
        session.flush()

        msg2 = session.get(ChatMessage, msg.id)
        assert msg2.action_status == "executed"

    def test_session_isolation(self, session):
        """Messages from one session don't leak to another."""
        svc = AIService(session)
        s1 = svc.create_session()
        s2 = svc.create_session()
        session.flush()

        svc.add_message(s1.id, "user", "s1 msg")
        svc.add_message(s2.id, "user", "s2 msg")
        session.flush()

        msgs1 = svc.get_messages(s1.id)
        msgs2 = svc.get_messages(s2.id)
        assert len(msgs1) == 1
        assert len(msgs2) == 1
        assert msgs1[0].content == "s1 msg"
        assert msgs2[0].content == "s2 msg"


class TestActionSpecs:
    def test_get_all_actions(self, session):
        svc = AIService(session)
        actions = svc.get_all_actions()
        assert "add_transaction" in actions
        assert "query_transactions" in actions
        assert "void_transaction" in actions

    def test_action_risk_levels(self, session):
        svc = AIService(session)
        query_spec = svc.get_action_spec("query_transactions")
        assert query_spec.risk_level == ActionRiskLevel.LOW
        assert not query_spec.requires_confirmation

        add_spec = svc.get_action_spec("add_transaction")
        assert add_spec.risk_level == ActionRiskLevel.MEDIUM
        assert add_spec.requires_confirmation

        void_spec = svc.get_action_spec("void_transaction")
        assert void_spec.risk_level == ActionRiskLevel.HIGH
        assert void_spec.requires_confirmation

    def test_validate_params_missing_required(self, session):
        svc = AIService(session)
        spec = svc.get_action_spec("add_transaction")

        errors = spec.validate_params(amount="100")
        assert len(errors) > 0
        assert any("type" in e.lower() for e in errors) or any("date" in e.lower() for e in errors)

    def test_validate_params_valid(self, session):
        svc = AIService(session)
        spec = svc.get_action_spec("add_transaction")

        errors = spec.validate_params(
            type="expense", amount="100", date="2025-07-01",
            category="餐饮", account="现金",
        )
        assert len(errors) == 0

    def test_validate_negative_amount(self, session):
        svc = AIService(session)
        spec = svc.get_action_spec("add_transaction")

        errors = spec.validate_params(
            type="expense", amount="-100", date="2025-07-01",
            category="餐饮", account="现金",
        )
        assert len(errors) > 0

    def test_validate_action_proposal(self, session):
        svc = AIService(session)
        proposal = ActionProposal(
            action="add_transaction",
            params={"type": "expense", "amount": "100", "date": "2025-07-01",
                     "category": "餐饮", "account": "现金"},
            risk_level=ActionRiskLevel.MEDIUM,
            summary="记录支出 ¥100",
        )
        errors = svc.validate_action_proposal(proposal)
        assert len(errors) == 0

    def test_validate_unknown_action(self, session):
        svc = AIService(session)
        proposal = ActionProposal(
            action="delete_database",
            params={},
            risk_level=ActionRiskLevel.HIGH,
            summary="危险操作",
        )
        errors = svc.validate_action_proposal(proposal)
        assert len(errors) > 0
        assert "未知" in errors[0]

    def test_action_proposal_serialization(self, session):
        proposal = ActionProposal(
            action="add_transaction",
            params={"type": "expense", "amount": "100"},
            risk_level=ActionRiskLevel.MEDIUM,
            summary="test",
        )
        d = proposal.to_dict()
        assert d["action"] == "add_transaction"
        assert d["risk_level"] == "medium"

        p2 = ActionProposal.from_json(d)
        assert p2.action == proposal.action
        assert p2.params == proposal.params


class TestActionExecution:
    def test_execute_query(self, session):
        svc = AIService(session)
        proposal = ActionProposal(
            action="query_transactions",
            params={"start_date": "2025-01-01", "end_date": "2025-12-31"},
            risk_level=ActionRiskLevel.LOW,
            summary="查询流水",
            requires_confirmation=False,
        )
        result = svc.execute_action(proposal, 1)
        assert result["success"]

    def test_execute_add_transaction_validation(self, session):
        svc = AIService(session)
        proposal = ActionProposal(
            action="add_transaction",
            params={"type": "expense"},  # missing required params
            risk_level=ActionRiskLevel.MEDIUM,
            summary="不完整的记账",
        )
        result = svc.execute_action(proposal, 1)
        assert not result["success"]

    def test_audit_logging(self, session):
        svc = AIService(session)
        proposal = ActionProposal(
            action="query_transactions",
            params={},
            risk_level=ActionRiskLevel.LOW,
            summary="测试查询",
        )
        result = svc.execute_action(proposal, 1)
        svc.record_audit("query_transactions", proposal, result)
        session.flush()

        from mym.domain.entities.audit import AuditLog
        logs = session.query(AuditLog).all()
        assert len(logs) > 0
        assert logs[0].source == "ai"
