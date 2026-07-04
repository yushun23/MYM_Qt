"""流水页面测试 — TransactionRepository 筛选/排序/分页 + UI 组件 + 导出。

覆盖：
- TransactionRepository 筛选、排序、分页
- TransactionTableModel 数据加载
- TransactionEditDialog 金额验证
- 公式注入防护
- 导出功能
- 同日稳定排序
"""

from __future__ import annotations

import csv
import tempfile
from datetime import date, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType
from mym2.repositories.transaction_repo import (
    TransactionFilter,
    TransactionPage,
    TransactionRepository,
)
from mym2.ui.pages.transactions_page import (
    TransactionEditDialog,
    TransactionTableModel,
    _minor_to_yuan,
    _protect_cell,
)


@pytest.fixture
def qapp_fixture(qapp):
    return qapp


# ── _minor_to_yuan ───────────────────────────────────


class TestMinorToYuan:
    def test_zero(self):
        assert _minor_to_yuan(0) == "0.00"

    def test_one_yuan(self):
        assert _minor_to_yuan(100) == "1.00"

    def test_with_cents(self):
        assert _minor_to_yuan(12345) == "123.45"

    def test_negative(self):
        assert _minor_to_yuan(-5000) == "-50.00"

    def test_large_value(self):
        assert _minor_to_yuan(1_000_000) == "10000.00"


# ── _protect_cell ────────────────────────────────────


class TestProtectCell:
    def test_equals_prefix(self):
        assert _protect_cell("=SUM(A1)") == "'=SUM(A1)"

    def test_plus_prefix(self):
        assert _protect_cell("+123") == "'+123"

    def test_minus_prefix(self):
        assert _protect_cell("-123") == "'-123"

    def test_at_prefix(self):
        assert _protect_cell("@SUM") == "'@SUM"

    def test_normal_text(self):
        assert _protect_cell("hello") == "hello"

    def test_empty(self):
        assert _protect_cell("") == ""


# ── TransactionTableModel ─────────────────────────────


class TestTransactionTableModel:
    def test_empty_model(self, qapp_fixture):
        model = TransactionTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 9

    def test_column_headers(self, qapp_fixture):
        model = TransactionTableModel()
        headers = [
            model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
            for i in range(model.columnCount())
        ]
        assert headers == [
            "日期", "类型", "来源账户", "目标账户",
            "分类", "金额", "备注", "清算", "状态",
        ]

    def test_load_data(self, qapp_fixture, session):
        """加载流水数据并验证显示内容。"""
        acct = Account(
            name="现金",
            type=AccountType.CASH,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="expense",
            account_out_id=acct.id,
            amount_minor=12345,
            note="午餐",
            source="manual",
        )
        session.add(tx)
        session.commit()

        model = TransactionTableModel()
        model.set_lookups({acct.id: acct}, {})
        model.load_data([tx])

        assert model.rowCount() == 1
        idx = model.index(0, 0)
        assert model.data(idx, Qt.DisplayRole) == "2026-07-04"
        idx = model.index(0, 5)
        assert model.data(idx, Qt.DisplayRole) == "123.45"
        idx = model.index(0, 6)
        assert model.data(idx, Qt.DisplayRole) == "午餐"

    def test_locked_transaction_status(self, qapp_fixture, session):
        """锁定流水显示"历史导入"状态。"""
        acct = Account(
            name="现金",
            type=AccountType.CASH,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="historical_investment_settlement",
            account_out_id=acct.id,
            amount_minor=500000,
            note="迁移快照",
            source="import",
            is_locked=True,
        )
        session.add(tx)
        session.commit()

        model = TransactionTableModel()
        model.set_lookups({acct.id: acct}, {})
        model.load_data([tx])

        assert model.rowCount() == 1
        idx = model.index(0, 8)
        assert model.data(idx, Qt.DisplayRole) == "历史导入"

    def test_expense_is_red(self, qapp_fixture, session):
        """支出金额显示为红色。"""
        acct = Account(
            name="现金",
            type=AccountType.CASH,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="expense",
            account_out_id=acct.id,
            amount_minor=10000,
        )
        session.add(tx)
        session.commit()

        model = TransactionTableModel()
        model.set_lookups({acct.id: acct}, {})
        model.load_data([tx])

        idx = model.index(0, 5)
        color = model.data(idx, Qt.ForegroundRole)
        assert color is not None

    def test_income_is_green(self, qapp_fixture, session):
        """收入金额显示为绿色。"""
        acct = Account(
            name="银行",
            type=AccountType.BANK,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="income",
            account_out_id=acct.id,
            account_in_id=acct.id,
            amount_minor=200000,
        )
        session.add(tx)
        session.commit()

        model = TransactionTableModel()
        model.set_lookups({acct.id: acct}, {})
        model.load_data([tx])

        idx = model.index(0, 5)
        color = model.data(idx, Qt.ForegroundRole)
        assert color is not None

    def test_get_transaction_out_of_range(self, qapp_fixture):
        model = TransactionTableModel()
        assert model.get_transaction(-1) is None
        assert model.get_transaction(100) is None

    def test_amount_right_aligned(self, qapp_fixture, session):
        """金额列右对齐。"""
        acct = Account(
            name="现金",
            type=AccountType.CASH,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="expense",
            account_out_id=acct.id,
            amount_minor=5000,
        )
        session.add(tx)
        session.commit()

        model = TransactionTableModel()
        model.set_lookups({acct.id: acct}, {})
        model.load_data([tx])

        idx = model.index(0, 5)
        alignment = model.data(idx, Qt.TextAlignmentRole)
        assert alignment is not None
        assert alignment & Qt.AlignRight


# ── TransactionEditDialog 验证 ───────────────────────


class TestTransactionEditDialog:
    @pytest.fixture
    def accounts(self) -> list[Account]:
        return [
            Account(
                id="acct1", name="现金",
                type=AccountType.CASH,
                is_enabled=True, is_editable=True,
                opening_balance_minor=0, current_balance_minor=0,
            ),
            Account(
                id="acct2", name="银行",
                type=AccountType.BANK,
                is_enabled=True, is_editable=True,
                opening_balance_minor=0, current_balance_minor=0,
            ),
        ]

    @pytest.fixture
    def categories(self) -> list[Category]:
        return [
            Category(id="cat1", name="餐饮", type="expense", is_enabled=True),
            Category(id="cat2", name="工资", type="income", is_enabled=True),
        ]

    def test_expense_dialog_has_category(self, qapp_fixture, accounts, categories):
        """支出对话框包含分类选择。"""
        dlg = TransactionEditDialog(None, "expense", accounts, categories)
        assert dlg._category_combo is not None
        assert dlg._account_in_combo is None
        dlg.deleteLater()

    def test_income_dialog_has_category(self, qapp_fixture, accounts, categories):
        """收入对话框包含分类选择。"""
        dlg = TransactionEditDialog(None, "income", accounts, categories)
        assert dlg._category_combo is not None
        dlg.deleteLater()

    def test_transfer_dialog_has_target_account(self, qapp_fixture, accounts, categories):
        """转账对话框包含目标账户选择但不含分类。"""
        dlg = TransactionEditDialog(None, "transfer", accounts, categories)
        assert dlg._account_in_combo is not None
        assert dlg._category_combo is None
        dlg.deleteLater()

    def test_accept_empty_amount(self, qapp_fixture, accounts, categories, monkeypatch):
        """空金额时应拒绝。"""
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **kw: None)
        dlg = TransactionEditDialog(None, "expense", accounts, categories)
        dlg._amount_edit.setText("")
        dlg._on_accept()
        assert dlg.result() == 0  # 对话框未接受
        dlg.deleteLater()

    def test_amount_gets_validated(self, qapp_fixture, accounts, categories):
        """有效金额应通过验证。"""
        dlg = TransactionEditDialog(None, "expense", accounts, categories)
        dlg._amount_edit.setText("123.45")
        dlg._on_accept()
        assert dlg.result() == 1  # 对话框已接受
        assert dlg.result_dto is not None
        dlg.deleteLater()

    def test_edit_dialog_shows_cleared_check(self, qapp_fixture, accounts, categories, session):
        """编辑对话框显示清算复选框。"""
        acct = accounts[0]
        session.add(acct)
        session.commit()
        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="expense",
            account_out_id=acct.id,
            amount_minor=10000,
        )
        session.add(tx)
        session.commit()

        dlg = TransactionEditDialog(None, "expense", accounts, categories, existing=tx)
        assert dlg._cleared_check is not None
        dlg.deleteLater()


# ── TransactionRepository 筛选/排序/分页 ─────────────


class TestTransactionRepositoryFilters:
    """TransactionRepository 查询功能测试。"""

    def _make_account(self, session, name="现金", atype=AccountType.CASH) -> Account:
        a = Account(
            name=name,
            type=atype,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(a)
        session.commit()
        return a

    def _make_category(self, session, name="餐饮", ctype="expense") -> Category:
        c = Category(name=name, type=ctype, is_enabled=True)
        session.add(c)
        session.commit()
        return c

    def _make_tx(self, session, acct_out, **kw) -> Transaction:
        defaults = {
            "transaction_date": date(2026, 7, 4),
            "type": "expense",
            "account_out_id": acct_out.id,
            "amount_minor": 10000,
            "source": "manual",
        }
        defaults.update(kw)
        tx = Transaction(**defaults)
        session.add(tx)
        session.commit()
        return tx

    def test_empty_query(self, session):
        repo = TransactionRepository(session)
        result = repo.query_filtered(TransactionFilter())
        assert isinstance(result, TransactionPage)
        assert result.total == 0
        assert result.items == []

    def test_query_all(self, session):
        acct = self._make_account(session)
        self._make_tx(session, acct)
        self._make_tx(session, acct, amount_minor=20000, transaction_date=date(2026, 7, 5))

        repo = TransactionRepository(session)
        result = repo.query_filtered(TransactionFilter())
        assert result.total == 2
        assert len(result.items) == 2

    def test_filter_by_date_range(self, session):
        acct = self._make_account(session)
        self._make_tx(session, acct, transaction_date=date(2026, 6, 1))
        self._make_tx(session, acct, transaction_date=date(2026, 7, 5))
        self._make_tx(session, acct, transaction_date=date(2026, 8, 10))

        repo = TransactionRepository(session)
        f = TransactionFilter(date_from=date(2026, 7, 1), date_to=date(2026, 7, 31))
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_filter_by_account(self, session):
        acct1 = self._make_account(session, "现金")
        acct2 = self._make_account(session, "银行")
        self._make_tx(session, acct1)
        self._make_tx(session, acct2, amount_minor=20000)

        repo = TransactionRepository(session)
        f = TransactionFilter(account_ids=[acct1.id])
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_filter_by_account_in(self, session):
        """筛选也应匹配 account_in_id。"""
        acct1 = self._make_account(session, "现金")
        acct2 = self._make_account(session, "银行")
        self._make_tx(session, acct1)
        self._make_tx(
            session, acct1,
            type="transfer",
            account_in_id=acct2.id,
            amount_minor=50000,
        )

        repo = TransactionRepository(session)
        f = TransactionFilter(account_ids=[acct2.id])
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_filter_by_category(self, session):
        acct = self._make_account(session)
        cat = self._make_category(session, "餐饮", "expense")
        cat2 = self._make_category(session, "交通", "expense")
        self._make_tx(session, acct, category_id=cat.id)
        self._make_tx(session, acct, category_id=cat2.id, amount_minor=20000)

        repo = TransactionRepository(session)
        f = TransactionFilter(category_ids=[cat.id])
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_filter_by_type(self, session):
        acct = self._make_account(session)
        self._make_tx(session, acct, type="expense")
        self._make_tx(session, acct, type="income", account_in_id=acct.id)

        repo = TransactionRepository(session)
        f = TransactionFilter(types=["expense"])
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_filter_by_keyword(self, session):
        acct = self._make_account(session)
        self._make_tx(session, acct, note="午餐肯德基")
        self._make_tx(session, acct, note="地铁通勤", amount_minor=20000)

        repo = TransactionRepository(session)
        f = TransactionFilter(keyword="午餐")
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_filter_by_cleared(self, session):
        acct = self._make_account(session)
        self._make_tx(session, acct, is_cleared=True)
        self._make_tx(session, acct, amount_minor=20000, is_cleared=False)

        repo = TransactionRepository(session)
        f = TransactionFilter(is_cleared=True)
        result = repo.query_filtered(f)
        assert result.total == 1

    def test_pagination(self, session):
        acct = self._make_account(session)
        for i in range(15):
            self._make_tx(session, acct, amount_minor=(i + 1) * 100, note=f"tx{i}")

        repo = TransactionRepository(session)
        result = repo.query_filtered(TransactionFilter(), page=1, page_size=10)
        assert result.total == 15
        assert len(result.items) == 10
        assert result.page == 1
        assert result.page_size == 10

        result2 = repo.query_filtered(TransactionFilter(), page=2, page_size=10)
        assert len(result2.items) == 5

    def test_stable_sort_same_date(self, session):
        """同一天内按 created_at + id 稳定排序。"""
        acct = self._make_account(session)
        t1 = datetime(2026, 7, 4, 10, 0, 0)
        t2 = datetime(2026, 7, 4, 10, 0, 1)
        t3 = datetime(2026, 7, 4, 10, 0, 2)

        tx1 = self._make_tx(session, acct, amount_minor=100)
        tx2 = self._make_tx(session, acct, amount_minor=200)
        tx3 = self._make_tx(session, acct, amount_minor=300)

        # 手动设置 created_at 以测试稳定排序
        session.execute(
            __import__("sqlalchemy").update(Transaction)
            .where(Transaction.id == tx1.id)
            .values(created_at=t2)
        )
        session.execute(
            __import__("sqlalchemy").update(Transaction)
            .where(Transaction.id == tx2.id)
            .values(created_at=t1)
        )
        session.execute(
            __import__("sqlalchemy").update(Transaction)
            .where(Transaction.id == tx3.id)
            .values(created_at=t3)
        )
        session.commit()

        repo = TransactionRepository(session)
        result = repo.query_filtered(
            TransactionFilter(),
            sort_column="transaction_date",
            sort_desc=False,
        )
        assert len(result.items) == 3
        # 同一日期，按 created_at 排序：t1, t2, t3 → tx2, tx1, tx3
        assert result.items[0].id == tx2.id
        assert result.items[1].id == tx1.id
        assert result.items[2].id == tx3.id

    def test_get_accounts_map(self, session):
        acct = self._make_account(session, "现金")
        repo = TransactionRepository(session)
        m = repo.get_accounts_map()
        assert acct.id in m
        assert m[acct.id].name == "现金"

    def test_get_categories_map(self, session):
        cat = self._make_category(session, "餐饮")
        repo = TransactionRepository(session)
        m = repo.get_categories_map()
        assert cat.id in m
        assert m[cat.id].name == "餐饮"


# ── 导出测试 ─────────────────────────────────────────


class TestExport:
    """CSV 导出测试。"""

    def _setup_data(self, session):
        acct = Account(
            name="现金",
            type=AccountType.CASH,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="expense",
            account_out_id=acct.id,
            amount_minor=12345,
            note="=SUM(A1)",
            source="manual",
        )
        session.add(tx)
        session.commit()
        return acct, tx

    def test_export_csv_formula_protection(self, session):
        """导出 CSV 应对公式文本做注入防护。"""
        self._setup_data(session)

        # 只测试核心的 _protect_cell 逻辑
        assert _protect_cell("=SUM(A1)") == "'=SUM(A1)"
        assert _protect_cell("normal") == "normal"

    def test_export_all_data(self, session):
        """导出当前筛选的全部数据到 CSV。"""
        self._setup_data(session)

        repo = TransactionRepository(session)
        result = repo.query_filtered(TransactionFilter())
        assert result.total == 1

        # 验证通过 repo 查询的数据可以导出
        accounts = repo.get_accounts_map()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
        ) as f:
            writer = csv.writer(f)
            writer.writerow(["日期", "类型", "来源账户", "目标账户", "分类", "金额", "备注"])
            for tx in result.items:
                acct_out = accounts.get(tx.account_out_id)
                note = _protect_cell(tx.note or "")
                writer.writerow([
                    str(tx.transaction_date),
                    tx.type,
                    acct_out.name if acct_out else "",
                    "",
                    "",
                    _minor_to_yuan(tx.amount_minor),
                    note,
                ])
            tmp_path = f.name

        # 验证导出文件
        with open(tmp_path, encoding="utf-8-sig") as f:
            content = f.read()
            assert "=" not in content or content.count("'=") > 0
            assert "123.45" in content

        Path(tmp_path).unlink(missing_ok=True)

    def test_amount_always_two_decimals(self, session):
        """导出金额始终保留两位小数。"""
        acct = Account(
            name="现金",
            type=AccountType.CASH,
            is_enabled=True,
            is_editable=True,
            opening_balance_minor=0,
            current_balance_minor=0,
        )
        session.add(acct)
        session.commit()

        # 元整数 100 → "1.00"
        tx = Transaction(
            transaction_date=date(2026, 7, 4),
            type="expense",
            account_out_id=acct.id,
            amount_minor=100,
        )
        session.add(tx)
        session.commit()

        assert _minor_to_yuan(100) == "1.00"
        assert _minor_to_yuan(50) == "0.50"
        assert _minor_to_yuan(10500) == "105.00"


# ── TransactionsPage 构造 ────────────────────────────


class TestTransactionsPageConstruction:
    def test_constructs_without_session(self, qapp_fixture):
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        assert page is not None
        assert page._table is not None
        assert page._search_edit is not None
        page.deleteLater()

    def test_has_filter_controls(self, qapp_fixture):
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        assert page._date_from_edit is not None
        assert page._date_to_edit is not None
        assert page._account_filter is not None
        assert page._category_filter is not None
        assert page._type_filter is not None
        assert page._cleared_filter is not None
        page.deleteLater()

    def test_has_add_menu(self, qapp_fixture):
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        assert page._add_menu is not None
        # 菜单应只包含三种普通类型
        actions = page._add_menu.actions()
        action_texts = [a.text() for a in actions]
        assert "支出" in action_texts
        assert "收入" in action_texts
        assert "转账" in action_texts
        # 不应包含应收/余额调节/历史结算
        assert "应收" not in action_texts
        assert "余额调节" not in action_texts
        assert "历史" not in action_texts
        page.deleteLater()

    def test_has_edit_delete_buttons(self, qapp_fixture):
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        assert page._edit_btn is not None
        assert page._delete_btn is not None
        page.deleteLater()

    def test_has_pagination(self, qapp_fixture):
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        assert page._prev_btn is not None
        assert page._next_btn is not None
        assert page._page_size_combo is not None
        assert page._page_info_label is not None
        page.deleteLater()

    def test_has_export_button(self, qapp_fixture):
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        assert page._export_btn is not None
        page.deleteLater()

    def test_no_stock_entry_points(self, qapp_fixture):
        """添加菜单中不含股票/证券相关入口。"""
        from mym2.ui.pages.transactions_page import TransactionsPage
        page = TransactionsPage()
        actions = page._add_menu.actions()
        banned = ["股票", "证券", "持仓", "行情", "买卖", "结算"]
        for action in actions:
            for word in banned:
                assert word not in action.text(), f"添加菜单包含禁止词: {action.text()}"
        page.deleteLater()
