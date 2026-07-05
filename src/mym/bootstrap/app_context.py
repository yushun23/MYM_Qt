"""Application context for an opened ledger.

This module keeps the runtime dependencies that are only available after a
ledger has been created or opened. UI pages receive this context (or the
session factory from it) instead of reaching into global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mym.application.services.ledger_lifecycle import LedgerLifecycle
from mym.infrastructure.app_config import AppConfig
from mym.infrastructure.database.db_manager import DatabaseManager
from mym.infrastructure.database.session import SessionFactory
from mym.infrastructure.i18n import I18nManager
from mym.ui.navigation import AppEventBus
from mym.ui.theme.theme_manager import ThemeManager


@dataclass(slots=True)
class AppContext:
    """Dependencies for the currently opened ledger."""

    config: AppConfig
    i18n: I18nManager
    theme: ThemeManager
    lifecycle: LedgerLifecycle
    db_manager: DatabaseManager
    event_bus: AppEventBus

    @property
    def ledger_path(self) -> Path:
        """Path of the currently opened ledger file."""
        return self.db_manager.ledger_path

    @property
    def session_factory(self) -> SessionFactory:
        """Create short-lived SQLAlchemy sessions for UI pages and services."""
        return self.db_manager.session_factory
