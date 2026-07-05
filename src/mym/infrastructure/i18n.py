"""Multi-language framework using JSON translation resources."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class I18nManager:
    """Manages translations loaded from JSON files."""

    def __init__(self, i18n_dir: Path) -> None:
        self._i18n_dir = i18n_dir
        self._translations: dict[str, dict[str, str]] = {}
        self._current_locale = "zh_CN"
        self._fallback_locale = "zh_CN"
        self._load_all()

    def _load_all(self) -> None:
        """Load all available translation files."""
        if not self._i18n_dir.exists():
            logger.warning("i18n directory not found: %s", self._i18n_dir)
            return
        for f in self._i18n_dir.glob("*.json"):
            locale = f.stem
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    self._translations[locale] = json.load(fh)
                logger.debug("Loaded translations: %s (%d keys)", locale, len(self._translations[locale]))
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load translation %s: %s", f, e)

    @property
    def available_locales(self) -> list[str]:
        """List of available locale codes."""
        return list(self._translations.keys())

    @property
    def current_locale(self) -> str:
        """Current locale code."""
        return self._current_locale

    def set_locale(self, locale: str) -> None:
        """Switch to a locale. Falls back silently if not found."""
        if locale in self._translations:
            self._current_locale = locale
            logger.info("Locale set to: %s", locale)
        else:
            logger.warning("Locale %s not available, keeping %s", locale, self._current_locale)

    def tr(self, key: str, default: str = "", **kwargs: Any) -> str:
        """Translate a key. Falls back to fallback locale, then key itself.

        Args:
            key: Translation key (e.g., 'menu.file').
            default: Default text if no translation found.
            **kwargs: Format parameters for the translated string.

        Returns:
            Translated string.
        """
        # Try current locale
        value = self._translations.get(self._current_locale, {}).get(key)
        if value is None:
            # Try fallback
            value = self._translations.get(self._fallback_locale, {}).get(key)
        if value is None:
            value = default or key
        if kwargs:
            try:
                value = value.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return value


# Module-level singleton placeholder – will be initialized by Application
_i18n: I18nManager | None = None


def get_i18n() -> I18nManager:
    """Get the global I18nManager singleton."""
    global _i18n
    if _i18n is None:
        raise RuntimeError("I18nManager not initialized. Call set_i18n() first.")
    return _i18n


def set_i18n(manager: I18nManager) -> None:
    """Set the global I18nManager singleton."""
    global _i18n
    _i18n = manager


def tr(key: str, default: str = "", **kwargs: Any) -> str:
    """Convenience function to translate a key."""
    return get_i18n().tr(key, default, **kwargs)
