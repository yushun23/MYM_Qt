"""P6: Regression tests for ledger scenarios."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.infrastructure.database.db_manager import DatabaseManager

# Import from the fixture module directly
import sys
sys.path.insert(0, '/Users/dexterskyowl/编程开发/MYM_Qt')
from tests.fixtures.ledger_scenarios import (
    scenario_credit_card_repayment,
    scenario_empty,
    scenario_multi_account_transfer,
    scenario_salary_and_dining,
)


@pytest.fixture
def session():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    s = mgr.new_session()
    yield s
    s.close()
    mgr.close()
    tmp_path.unlink(missing_ok=True)


def test_empty_ledger(session: Session) -> None:
    result = scenario_empty(session)
    assert len(result["accounts"]) >= 1


def test_salary_and_dining(session: Session) -> None:
    result = scenario_salary_and_dining(session)
    session.refresh(result["bank"])
    assert result["bank"].current_balance == result["expected_bank_balance"]


def test_multi_account_transfer(session: Session) -> None:
    result = scenario_multi_account_transfer(session)
    session.refresh(result["bank_a"])
    session.refresh(result["bank_b"])
    assert result["bank_a"].current_balance == result["expected_a_balance"]
    assert result["bank_b"].current_balance == result["expected_b_balance"]


def test_credit_card_repayment(session: Session) -> None:
    result = scenario_credit_card_repayment(session)
    session.refresh(result["bank"])
    session.refresh(result["card"])
    assert result["bank"].current_balance == result["expected_bank_balance"]
    assert result["card"].current_balance == result["expected_card_balance"]
