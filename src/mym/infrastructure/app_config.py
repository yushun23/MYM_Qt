"""User-level application configuration backed by QSettings."""

import logging
from pathlib import Path

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "theme/mode": "light",
    "language/locale": "zh_CN",
    "window/width": 1200,
    "window/height": 800,
    "window/maximized": False,
    "recent/ledgers": "",
    "export/default_dir": "",
}


class AppConfig:
    """Wraps QSettings for user-level configuration."""

    def __init__(self) -> None:
        self._settings = QSettings("MYM", "MYM")

    def get(self, key: str) -> str:
        """Get a config value, returning default if not set."""
        return self._settings.value(key, _DEFAULTS.get(key, ""))

    def get_bool(self, key: str) -> bool:
        val = self.get(key)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")

    def get_int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (ValueError, TypeError):
            return int(_DEFAULTS.get(key, 0))

    def set(self, key: str, value: str | bool | int) -> None:
        """Set a config value."""
        self._settings.setValue(key, value)

    def get_recent_ledgers(self) -> list[str]:
        """Get list of recently opened ledgers."""
        raw = self.get("recent/ledgers")
        if not raw:
            return []
        return [p for p in str(raw).split("|") if p]

    def add_recent_ledger(self, path: str) -> None:
        """Add a ledger path to recent list (max 10, most recent first)."""
        recent = self.get_recent_ledgers()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self.set("recent/ledgers", "|".join(recent[:10]))

    def reset(self) -> None:
        """Reset all settings to defaults."""
        self._settings.clear()
        logger.info("Settings reset to defaults")

    def save_window_state(self, width: int, height: int, maximized: bool) -> None:
        self.set("window/width", width)
        self.set("window/height", height)
        self.set("window/maximized", maximized)


# Singleton
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
