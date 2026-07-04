"""UI 页面测试。"""


import pytest
from PySide6.QtCore import Qt

from mym2.ui.pages.accounts_page import (
    AccountsPage,
    AccountTableModel,
)
from mym2.ui.pages.categories_page import (
    CategoriesPage,
    CategoryTableModel,
)
from mym2.ui.pages.history_archive_page import (
    ArchiveRecordTableModel,
    HistoryArchivePage,
    ImportRunTableModel,
)
from mym2.ui.pages.settings_page import SettingsPage


@pytest.fixture
def qapp(qapp):
    """确保有 QApplication。"""
    return qapp


# ── 模型测试 ──────────────────────────────────────

class TestAccountTableModel:
    def test_empty_model(self):
        model = AccountTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 7
        assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "名称"

    def test_column_headers(self):
        model = AccountTableModel()
        headers = [
            model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
            for i in range(model.columnCount())
        ]
        assert headers == ["名称", "类型", "分组", "期初余额", "当前余额", "状态", "币种"]

    def test_get_account_out_of_range(self):
        model = AccountTableModel()
        assert model.get_account(-1) is None
        assert model.get_account(100) is None


class TestCategoryTableModel:
    def test_empty_model(self):
        model = CategoryTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 6

    def test_column_headers(self):
        model = CategoryTableModel()
        headers = [
            model.headerData(i, Qt.Horizontal, Qt.DisplayRole)
            for i in range(model.columnCount())
        ]
        assert "名称" in headers
        assert "类型" in headers


class TestImportRunTableModel:
    def test_empty_model(self):
        model = ImportRunTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 7


class TestArchiveRecordTableModel:
    def test_empty_model(self):
        model = ArchiveRecordTableModel()
        assert model.rowCount() == 0
        assert model.columnCount() == 3


# ── 页面构造测试 ──────────────────────────────────

class TestAccountsPage:
    def test_constructs_without_session(self, qapp):
        """账户页在无 session factory 时也能构造（延迟加载）。"""
        page = AccountsPage()
        assert page is not None
        page.deleteLater()

    def test_has_table_view(self, qapp):
        page = AccountsPage()
        assert page._table is not None
        page.deleteLater()

    def test_has_search(self, qapp):
        page = AccountsPage()
        assert page._search_edit is not None
        page.deleteLater()

    def test_navigate_to_signal_exists(self, qapp):
        page = AccountsPage()
        assert hasattr(page, "navigate_to")
        page.deleteLater()


class TestCategoriesPage:
    def test_constructs_without_session(self, qapp):
        page = CategoriesPage()
        assert page is not None
        page.deleteLater()

    def test_has_table_view(self, qapp):
        page = CategoriesPage()
        assert page._table is not None
        page.deleteLater()


class TestHistoryArchivePage:
    def test_constructs_without_session(self, qapp):
        page = HistoryArchivePage()
        assert page is not None
        page.deleteLater()

    def test_has_tabs(self, qapp):
        page = HistoryArchivePage()
        assert page._tabs.count() == 2
        page.deleteLater()

    def test_no_stock_terms_in_tab_labels(self, qapp):
        """验证归档页面不包含股票相关标签。"""
        page = HistoryArchivePage()
        banned = ["持仓", "行情", "买卖", "证券月结", "交易", "K线"]
        for i in range(page._tabs.count()):
            label = page._tabs.tabText(i)
            for word in banned:
                assert word not in label, f"归档页面包含禁止词: {word}"
        page.deleteLater()


class TestSettingsPage:
    def test_constructs(self, qapp):
        page = SettingsPage()
        assert page is not None
        page.deleteLater()

    def test_has_navigate_to_signal(self, qapp):
        page = SettingsPage()
        assert hasattr(page, "navigate_to")
        page.deleteLater()


# ── 导航词检查 ────────────────────────────────────

def test_no_stock_in_nav_items(qapp):
    """验证导航栏不包含股票字样。"""
    from mym2.ui.main_window import NAV_ITEMS

    nav_labels = [label for label, _, _ in NAV_ITEMS]
    banned = ["股票", "证券", "行情", "持仓", "交易", "stock", "invest"]

    for label in nav_labels:
        for word in banned:
            assert word not in label.lower(), f"导航包含禁止词: {label}"


def test_history_archive_has_correct_note(qapp):
    """验证历史归档页面说明包含正确措辞。"""
    page = HistoryArchivePage()
    # 遍历子控件查找说明标签
    found_note = False
    from PySide6.QtWidgets import QLabel
    for child in page.findChildren(QLabel):
        text = child.text()
        if "不提供" in text and ("持仓" in text or "行情" in text):
            found_note = True
            break
    assert found_note, "历史归档页面缺少功能限制说明"
    page.deleteLater()
