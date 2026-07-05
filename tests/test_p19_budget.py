"""Tests for P19 – Budget domain, repository, and service."""

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.budget_service import BudgetService
from mym.domain.entities.budget import BudgetPeriod, BudgetLine
from mym.domain.entities.account import Account
from mym.domain.entities.category import Category
from mym.domain.enums import (
    AccountType, BudgetStatus, CategoryType, TransactionSource, TransactionStatus,
)
from mym.infrastructure.database.db_manager import DatabaseManager
from mym.infrastructure.repositories.budget_repo import BudgetRepository


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


class TestBudgetRepository:
    def test_create_and_get_period(self, session):
        repo = BudgetRepository(session)
        period = BudgetPeriod(year=2025, month=7, status=BudgetStatus.OPEN)
        repo.add_period(period)
        session.flush()

        fetched = repo.get_period(period.id)
        assert fetched is not None
        assert fetched.year == 2025
        assert fetched.month == 7
        assert fetched.period_label == "2025-07"

    def test_get_by_ym(self, session):
        repo = BudgetRepository(session)
        period = BudgetPeriod(year=2025, month=8, status=BudgetStatus.OPEN)
        repo.add_period(period)
        session.flush()

        found = repo.get_period_by_ym(2025, 8)
        assert found is not None
        assert found.id == period.id

        not_found = repo.get_period_by_ym(2025, 9)
        assert not_found is None

    def test_list_periods(self, session):
        repo = BudgetRepository(session)
        repo.add_period(BudgetPeriod(year=2025, month=1, status=BudgetStatus.OPEN))
        repo.add_period(BudgetPeriod(year=2025, month=2, status=BudgetStatus.CLOSED))
        repo.add_period(BudgetPeriod(year=2024, month=12, status=BudgetStatus.OPEN))
        session.flush()

        all_p = repo.list_periods()
        assert len(all_p) == 3

        y2025 = repo.list_periods(year=2025)
        assert len(y2025) == 2

        closed = repo.list_periods(status=BudgetStatus.CLOSED)
        assert len(closed) == 1

    def test_add_and_get_lines(self, session):
        repo = BudgetRepository(session)
        period = BudgetPeriod(year=2025, month=7, status=BudgetStatus.OPEN)
        repo.add_period(period)
        session.flush()

        line = BudgetLine(
            period_id=period.id, name="餐饮", budget_type="expense",
            planned_amount=Decimal("3000"), sort_order=1,
        )
        repo.add_line(line)
        session.flush()

        lines = repo.get_lines_by_period(period.id)
        assert len(lines) == 1
        assert lines[0].name == "餐饮"

    def test_get_root_lines(self, session):
        repo = BudgetRepository(session)
        period = BudgetPeriod(year=2025, month=7, status=BudgetStatus.OPEN)
        repo.add_period(period)
        session.flush()

        root = BudgetLine(
            period_id=period.id, name="日常", budget_type="expense",
            planned_amount=Decimal("5000"), is_group=True, sort_order=1,
        )
        repo.add_line(root)
        session.flush()

        child = BudgetLine(
            period_id=period.id, parent_id=root.id, name="餐饮",
            budget_type="expense", planned_amount=Decimal("3000"), sort_order=1,
        )
        repo.add_line(child)
        session.flush()

        roots = repo.get_root_lines(period.id)
        assert len(roots) == 1
        assert roots[0].name == "日常"

        children = repo.get_children(root.id)
        assert len(children) == 1
        assert children[0].name == "餐饮"

    def test_get_total_planned(self, session):
        repo = BudgetRepository(session)
        period = BudgetPeriod(year=2025, month=7, status=BudgetStatus.OPEN)
        repo.add_period(period)
        session.flush()

        for name, amt in [("餐饮", "3000"), ("交通", "1000"), ("总计", "5000")]:
            is_group = name == "总计"
            repo.add_line(BudgetLine(
                period_id=period.id, name=name, budget_type="expense",
                planned_amount=Decimal(amt), is_group=is_group,
            ))
        session.flush()

        total = repo.get_total_planned(period.id, "expense")
        assert total == Decimal("4000")  # only non-group lines


class TestBudgetService:
    def _setup_categories(self, session):
        for name, ctype in [("工资", CategoryType.INCOME), ("餐饮", CategoryType.EXPENSE)]:
            cat = Category(name=name, category_type=ctype)
            session.add(cat)
        session.flush()

    def test_create_period(self, session):
        svc = BudgetService(session)
        result = svc.create_period(2025, 7)
        assert result.success
        assert result.period_id is not None

        # Duplicate
        result2 = svc.create_period(2025, 7)
        assert not result2.success

    def test_copy_from_month(self, session):
        self._setup_categories(session)
        svc = BudgetService(session)

        # Create source period with lines
        src = svc.create_period(2025, 6)
        session.flush()
        svc.add_line(src.period_id, "餐饮", "expense", Decimal("3000"))
        svc.add_line(src.period_id, "交通", "expense", Decimal("1000"))
        session.flush()

        # Copy
        result = svc.copy_from_month(2025, 6, 2025, 7)
        assert result.success

        repo = BudgetRepository(session)
        target = repo.get_period(result.period_id)
        assert target is not None
        lines = repo.get_lines_by_period(target.id)
        assert len(lines) == 2

    def test_close_and_reopen(self, session):
        svc = BudgetService(session)
        result = svc.create_period(2025, 7)
        session.flush()

        # Close
        close_result = svc.close_period(result.period_id)
        assert close_result.success

        repo = BudgetRepository(session)
        period = repo.get_period(result.period_id)
        assert period.status == BudgetStatus.CLOSED

        # Cannot add line to closed period
        add_result = svc.add_line(result.period_id, "测试", "expense", Decimal("100"))
        assert not add_result.success

        # Reopen
        reopen_result = svc.reopen_period(result.period_id)
        assert reopen_result.success

        period = repo.get_period(result.period_id)
        assert period.status == BudgetStatus.OPEN

    def test_add_line_and_tree(self, session):
        self._setup_categories(session)
        svc = BudgetService(session)
        result = svc.create_period(2025, 7)
        session.flush()

        # Add group
        group = svc.add_line(
            result.period_id, "日常消费", "expense",
            Decimal("5000"), is_group=True, sort_order=1,
        )
        assert group.success

        # Add children
        svc.add_line(
            result.period_id, "餐饮", "expense",
            Decimal("3000"), parent_id=group.line_id, sort_order=1,
        )
        svc.add_line(
            result.period_id, "交通", "expense",
            Decimal("2000"), parent_id=group.line_id, sort_order=2,
        )
        session.flush()

        # Get summary
        summaries = svc.get_period_summary(result.period_id)
        assert len(summaries) == 1  # root group
        assert summaries[0].name == "日常消费"
        assert summaries[0].planned_amount == Decimal("5000")
        assert len(summaries[0].children) == 2

    def test_delete_line(self, session):
        svc = BudgetService(session)
        result = svc.create_period(2025, 7)
        session.flush()
        line = svc.add_line(result.period_id, "餐饮", "expense", Decimal("3000"))
        session.flush()

        del_result = svc.delete_line(line.line_id)
        assert del_result.success

        repo = BudgetRepository(session)
        lines = repo.get_lines_by_period(result.period_id)
        assert len(lines) == 0

    def test_over_budget_detection(self, session):
        self._setup_categories(session)
        svc = BudgetService(session)
        result = svc.create_period(2025, 7)
        session.flush()
        svc.add_line(
            result.period_id, "餐饮", "expense",
            Decimal("1000"), warn_threshold_pct=80,
        )
        session.flush()

        # Summary with no actuals
        summaries = svc.get_period_summary(result.period_id)
        assert summaries[0].execution_pct == Decimal("0")
        assert not summaries[0].is_over_budget
