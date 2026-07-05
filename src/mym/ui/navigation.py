"""Navigation framework: page container, event bus, page lifecycle."""

import logging
from enum import Enum

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QStackedWidget, QWidget

logger = logging.getLogger(__name__)


class PageKey(str, Enum):
    DASHBOARD = "dashboard"
    RECORD = "record"
    TRANSACTIONS = "transactions"
    ACCOUNTS = "accounts"
    REPORTS = "reports"
    BUDGET = "budget"
    RECEIVABLE = "receivable"
    AI = "ai"
    SETTINGS = "settings"


class AppEventBus(QObject):
    """Global application event bus."""

    ledger_changed = Signal()
    settings_changed = Signal()
    module_visibility_changed = Signal()
    import_finished = Signal()
    budget_changed = Signal()
    investment_changed = Signal()

    _instance = None

    @classmethod
    def instance(cls) -> "AppEventBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


class NavigationManager:
    """Manages page navigation and lifecycle."""

    def __init__(self, stacked_widget: QStackedWidget, event_bus: AppEventBus) -> None:
        self._stack = stacked_widget
        self._event_bus = event_bus
        self._pages: dict[PageKey, QWidget] = {}
        self._current_key: PageKey | None = None

    def register(self, key: PageKey, page: QWidget) -> None:
        self._pages[key] = page
        self._stack.addWidget(page)

    def navigate(self, key: PageKey) -> None:
        if key not in self._pages:
            logger.warning("Page not registered: %s", key)
            return
        page = self._pages[key]
        # Call on_enter if exists
        if hasattr(page, "on_enter"):
            page.on_enter()
        self._stack.setCurrentWidget(page)
        # Call on_leave on previous
        if self._current_key and self._current_key in self._pages:
            prev = self._pages[self._current_key]
            if hasattr(prev, "on_leave"):
                prev.on_leave()
        self._current_key = key
        logger.debug("Navigated to: %s", key.value)

    def current_key(self) -> PageKey | None:
        return self._current_key

    def is_visible(self, key: PageKey) -> bool:
        return key in self._pages and self._stack.indexOf(self._pages[key]) >= 0

    def hide_module(self, key: PageKey) -> None:
        if key in self._pages:
            self._stack.removeWidget(self._pages[key])
            self._event_bus.module_visibility_changed.emit()

    def show_module(self, key: PageKey) -> None:
        if key in self._pages and self._stack.indexOf(self._pages[key]) < 0:
            self._stack.addWidget(self._pages[key])
            self._event_bus.module_visibility_changed.emit()
