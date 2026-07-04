"""MYM2 UI 页面模块。"""

from mym2.ui.pages.accounts_page import AccountsPage
from mym2.ui.pages.budget_page import BudgetPage
from mym2.ui.pages.categories_page import CategoriesPage
from mym2.ui.pages.dashboard_page import DashboardPage
from mym2.ui.pages.history_archive_page import HistoryArchivePage
from mym2.ui.pages.import_wizard import ImportWizard
from mym2.ui.pages.receivables_page import ReceivablesPage
from mym2.ui.pages.reports_page import ReportsPage
from mym2.ui.pages.settings_page import SettingsPage
from mym2.ui.pages.transactions_page import TransactionsPage

__all__ = [
    "AccountsPage",
    "BudgetPage",
    "CategoriesPage",
    "DashboardPage",
    "HistoryArchivePage",
    "ImportWizard",
    "ReceivablesPage",
    "ReportsPage",
    "SettingsPage",
    "TransactionsPage",
]
