"""Main window wiring ledger lifecycle, navigation and pages."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.ledger_lifecycle import LedgerLifecycle
from mym.bootstrap.app_context import AppContext
from mym.infrastructure.app_config import AppConfig
from mym.infrastructure.i18n import I18nManager
from mym.infrastructure.paths.app_paths import get_backup_dir, get_ledger_dir
from mym.ui.navigation import AppEventBus, NavigationManager, PageKey
from mym.ui.pages.welcome_page import WelcomePage
from mym.ui.theme.theme_manager import ThemeManager
from mym.ui.widgets.migration_wizard import MigrationWizard

logger = logging.getLogger(__name__)


class _UnavailablePage(QWidget):
    """Fallback page used when a module fails to initialize."""

    def __init__(self, title: str, error: Exception, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(f"{title} 暂时不可用。\n\n{type(error).__name__}: {error}")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #D32F2F; font-size: 14px;")
        layout.addWidget(label)
        logger.exception("Failed to create page %s: %s", title, error)


class MainWindow(QMainWindow):
    """Application main window.

    Before a ledger is open this shows :class:`WelcomePage`. After creation or
    opening it builds an :class:`AppContext`, registers business pages, and shows
    the navigation shell.
    """

    def __init__(self, config: AppConfig, i18n: I18nManager, theme: ThemeManager) -> None:
        super().__init__()
        self._config = config
        self._i18n = i18n
        self._theme = theme
        self._event_bus = AppEventBus.instance()
        self._lifecycle = LedgerLifecycle(get_backup_dir())
        self._context: AppContext | None = None
        self._navigation: NavigationManager | None = None
        self._view_actions: dict[PageKey, QAction] = {}

        self.setWindowTitle(i18n.tr("app.title"))
        self._restore_window_state()
        self._apply_theme()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_central_widget()
        self._update_actions()

        self._theme.theme_changed.connect(self._on_theme_changed)

    @property
    def app_context(self) -> AppContext | None:
        """Current opened-ledger context, if any."""
        return self._context

    def _restore_window_state(self) -> None:
        self.resize(self._config.get_int("window/width"), self._config.get_int("window/height"))
        if self._config.get_bool("window/maximized"):
            self.showMaximized()

    def _apply_theme(self) -> None:
        self.setStyleSheet(self._theme.build_stylesheet())

    def _on_theme_changed(self, _colors: object) -> None:
        self._apply_theme()

    def _setup_menu_bar(self) -> None:
        menubar = self.menuBar()
        t = self._i18n.tr

        file_menu = menubar.addMenu(t("menu.file"))
        self._new_action = QAction(t("menu.file.new"), self)
        self._new_action.triggered.connect(lambda _checked=False: self.create_ledger())
        file_menu.addAction(self._new_action)

        self._open_action = QAction(t("menu.file.open"), self)
        self._open_action.triggered.connect(lambda _checked=False: self.open_ledger())
        file_menu.addAction(self._open_action)

        self._migrate_action = QAction(t("menu.file.migrate"), self)
        self._migrate_action.triggered.connect(lambda _checked=False: self.open_migration_wizard())
        file_menu.addAction(self._migrate_action)

        file_menu.addSeparator()
        self._close_ledger_action = QAction(t("menu.file.close_ledger"), self)
        self._close_ledger_action.triggered.connect(lambda _checked=False: self.close_ledger())
        file_menu.addAction(self._close_ledger_action)

        file_menu.addSeparator()
        exit_action = QAction(t("menu.file.exit"), self)
        exit_action.triggered.connect(lambda _checked=False: self.close())
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu(t("menu.view"))
        self._view_actions = {
            PageKey.DASHBOARD: QAction(t("menu.view.dashboard"), self),
            PageKey.RECORD: QAction(t("menu.view.record"), self),
            PageKey.TRANSACTIONS: QAction(t("menu.view.transactions"), self),
            PageKey.ACCOUNTS: QAction(t("menu.view.accounts"), self),
            PageKey.RECEIVABLE: QAction(t("menu.view.receivable"), self),
            PageKey.BUDGET: QAction(t("menu.view.budget"), self),
            PageKey.REPORTS: QAction(t("menu.view.reports"), self),
            PageKey.AI: QAction(t("menu.view.ai"), self),
            PageKey.SETTINGS: QAction(t("menu.view.settings"), self),
        }
        for key, action in self._view_actions.items():
            action.triggered.connect(lambda _checked=False, k=key: self.navigate(k))
            view_menu.addAction(action)

        help_menu = menubar.addMenu(t("menu.help"))
        about_action = QAction(t("menu.help.about"), self)
        about_action.triggered.connect(lambda _checked=False: self._show_about())
        help_menu.addAction(about_action)

    def _setup_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(self._i18n.tr("app.ready"))

    def _setup_central_widget(self) -> None:
        self._root_stack = QStackedWidget()
        self.setCentralWidget(self._root_stack)

        self._welcome_page = WelcomePage(self._config, self._i18n)
        self._welcome_page.create_ledger_requested.connect(self.create_ledger)
        self._welcome_page.open_ledger_requested.connect(self.open_ledger)
        self._welcome_page.migrate_legacy_requested.connect(self.open_migration_wizard)
        self._welcome_page.open_recent_requested.connect(lambda p: self.open_ledger(Path(p)))
        self._root_stack.addWidget(self._welcome_page)

        self._ledger_shell = QWidget()
        shell_layout = QHBoxLayout(self._ledger_shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self._nav_list = QListWidget()
        self._nav_list.setFixedWidth(180)
        self._nav_list.currentItemChanged.connect(self._on_nav_item_changed)
        shell_layout.addWidget(self._nav_list)

        self._page_stack = QStackedWidget()
        shell_layout.addWidget(self._page_stack, 1)
        self._root_stack.addWidget(self._ledger_shell)

        self._root_stack.setCurrentWidget(self._welcome_page)

    def create_ledger(self) -> bool:
        """Create a new ledger and enter the main navigation shell."""
        default_path = get_ledger_dir() / "新账本.mym"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            self._i18n.tr("dialog.create_ledger.title"),
            str(default_path),
            self._i18n.tr("dialog.ledger.filter"),
        )
        if not path_str:
            return False

        path = self._normalise_ledger_path(Path(path_str))
        if path.exists():
            QMessageBox.warning(self, self._i18n.tr("common.warning"), self._i18n.tr("dialog.create_ledger.exists"))
            return False

        try:
            self.close_ledger(silent=True)
            manager = self._lifecycle.create(path)
            self._on_ledger_opened(manager)
            self.status_bar.showMessage(self._i18n.tr("status.ledger_created"), 5000)
            return True
        except Exception as exc:  # noqa: BLE001 - UI boundary needs to show user-readable errors
            logger.exception("Create ledger failed: %s", exc)
            QMessageBox.critical(self, self._i18n.tr("common.error"), f"{self._i18n.tr('dialog.create_ledger.failed')}\n{exc}")
            return False

    def open_ledger(self, path: Path | None = None) -> bool:
        """Open an existing ledger and enter the main navigation shell."""
        if path is None:
            path_str, _ = QFileDialog.getOpenFileName(
                self,
                self._i18n.tr("dialog.open_ledger.title"),
                str(get_ledger_dir()),
                self._i18n.tr("dialog.ledger.filter"),
            )
            if not path_str:
                return False
            path = Path(path_str)

        if not path.exists():
            QMessageBox.warning(self, self._i18n.tr("common.warning"), self._i18n.tr("dialog.open_ledger.missing"))
            self._welcome_page.refresh_recent_ledgers()
            return False

        try:
            self.close_ledger(silent=True)
            manager = self._lifecycle.open(path)
            self._on_ledger_opened(manager)
            self.status_bar.showMessage(self._i18n.tr("status.ledger_opened"), 5000)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Open ledger failed: %s", exc)
            QMessageBox.critical(self, self._i18n.tr("common.error"), f"{self._i18n.tr('dialog.open_ledger.failed')}\n{exc}")
            self._show_welcome()
            return False

    def close_ledger(self, *, silent: bool = False) -> None:
        """Close the currently opened ledger and return to the welcome page."""
        if self._context is None and not self._lifecycle.is_open:
            return
        try:
            if self._lifecycle.is_open:
                self._lifecycle.close(backup=not silent)
        finally:
            self._context = None
            self._navigation = None
            self._clear_pages()
            self._show_welcome()
            self._update_actions()

    def open_migration_wizard(self) -> None:
        """Open legacy migration entry point.

        Current migrator implementation imports old data into an already opened
        target ledger, so when no ledger is open we first ask the user to create
        or open the target ledger.
        """
        if self._context is None:
            reply = QMessageBox.question(
                self,
                self._i18n.tr("migration.need_target.title"),
                self._i18n.tr("migration.need_target.message"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            if not self.create_ledger():
                return

        if self._context is None:
            return

        dialog = MigrationWizard(self._context.session_factory, self)
        dialog.migration_complete.connect(lambda _result: self._event_bus.ledger_changed.emit())
        dialog.exec()

    def navigate(self, key: PageKey) -> None:
        if self._navigation is None:
            return
        self._navigation.navigate(key)
        self._select_nav_item(key)

    def _on_ledger_opened(self, manager) -> None:  # type: ignore[no-untyped-def]
        self._context = AppContext(
            config=self._config,
            i18n=self._i18n,
            theme=self._theme,
            lifecycle=self._lifecycle,
            db_manager=manager,
            event_bus=self._event_bus,
        )
        self._config.add_recent_ledger(str(manager.ledger_path))
        self._welcome_page.refresh_recent_ledgers()
        self._build_pages(self._context)
        self._root_stack.setCurrentWidget(self._ledger_shell)
        self._update_actions()
        self.navigate(PageKey.DASHBOARD)
        self.status_bar.showMessage(f"{self._i18n.tr('status.current_ledger')}: {manager.ledger_path.name}")

    def _show_welcome(self) -> None:
        self._welcome_page.refresh_recent_ledgers()
        self._root_stack.setCurrentWidget(self._welcome_page)
        self.status_bar.showMessage(self._i18n.tr("app.ready"))

    def _build_pages(self, context: AppContext) -> None:
        self._clear_pages()
        self._navigation = NavigationManager(self._page_stack, self._event_bus)

        page_specs: list[tuple[PageKey, str, Callable[[], QWidget]]] = [
            (PageKey.DASHBOARD, self._i18n.tr("menu.view.dashboard"), lambda: self._create_dashboard_page(context)),
            (PageKey.RECORD, self._i18n.tr("menu.view.record"), lambda: self._create_record_page(context)),
            (PageKey.TRANSACTIONS, self._i18n.tr("menu.view.transactions"), lambda: self._create_transaction_page(context)),
            (PageKey.ACCOUNTS, self._i18n.tr("menu.view.accounts"), lambda: self._create_accounts_page(context)),
            (PageKey.RECEIVABLE, self._i18n.tr("menu.view.receivable"), lambda: self._create_receivable_page(context)),
            (PageKey.BUDGET, self._i18n.tr("menu.view.budget"), lambda: self._create_budget_page(context)),
            (PageKey.REPORTS, self._i18n.tr("menu.view.reports"), lambda: self._create_report_page(context)),
            (PageKey.AI, self._i18n.tr("menu.view.ai"), lambda: self._create_ai_page(context)),
            (PageKey.SETTINGS, self._i18n.tr("menu.view.settings"), lambda: self._create_settings_page(context)),
        ]

        for key, label, factory in page_specs:
            try:
                page = factory()
            except Exception as exc:  # noqa: BLE001
                page = _UnavailablePage(label.replace("&", ""), exc)
            self._navigation.register(key, page)
            self._add_nav_item(key, label)

    def _clear_pages(self) -> None:
        self._nav_list.clear()
        while self._page_stack.count():
            widget = self._page_stack.widget(0)
            self._page_stack.removeWidget(widget)
            widget.deleteLater()

    def _add_nav_item(self, key: PageKey, label: str) -> None:
        item = QListWidgetItem(label.replace("&", ""))
        item.setData(Qt.ItemDataRole.UserRole, key.value)
        self._nav_list.addItem(item)

    def _on_nav_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None or self._navigation is None:
            return
        raw_key = current.data(Qt.ItemDataRole.UserRole)
        try:
            key = PageKey(raw_key)
        except ValueError:
            return
        if self._navigation.current_key() != key:
            self._navigation.navigate(key)

    def _select_nav_item(self, key: PageKey) -> None:
        for row in range(self._nav_list.count()):
            item = self._nav_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == key.value:
                if self._nav_list.currentRow() != row:
                    self._nav_list.setCurrentRow(row)
                break

    def _create_dashboard_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.dashboard_page import DashboardPage

        return DashboardPage(context.session_factory)

    def _create_record_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.record_page import RecordPage

        return RecordPage(context.session_factory)

    def _create_transaction_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.transaction_page import TransactionPage

        return TransactionPage(context.session_factory)

    def _create_accounts_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.accounts_page import AccountCategoryPage

        return AccountCategoryPage(context.session_factory)

    def _create_receivable_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.receivable_page import ReceivablePage

        return ReceivablePage(context.session_factory)

    def _create_budget_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.budget_page import BudgetPage

        return BudgetPage(context.session_factory)

    def _create_report_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.report_page import ReportPage

        return ReportPage(context.session_factory)


    def _create_ai_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.ai_page import AIPage

        return AIPage(context.session_factory)

    def _create_settings_page(self, context: AppContext) -> QWidget:
        from mym.ui.pages.settings_page import SettingsPage

        return SettingsPage(context.session_factory, self._theme)

    def _update_actions(self) -> None:
        has_ledger = self._context is not None
        self._close_ledger_action.setEnabled(has_ledger)
        for key, action in self._view_actions.items():
            action.setEnabled(has_ledger)

    def _normalise_ledger_path(self, path: Path) -> Path:
        if path.suffix:
            return path
        return path.with_suffix(".mym")

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self._i18n.tr("menu.help.about"),
            f"{self._i18n.tr('app.title')}\n\n{self._i18n.tr('about.text')}",
        )

    def closeEvent(self, event: object) -> None:
        """Save window state and close the opened ledger safely."""
        self._config.save_window_state(self.width(), self.height(), self.isMaximized())
        try:
            if self._lifecycle.is_open:
                self._lifecycle.close(backup=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to close ledger during app shutdown: %s", exc)
        super().closeEvent(event)
