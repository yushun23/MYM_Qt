"""MYM Application entry point."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mym.infrastructure.app_config import get_config
from mym.infrastructure.i18n import I18nManager, set_i18n
from mym.infrastructure.logging_config.logger import setup_logging
from mym.infrastructure.paths.app_paths import ensure_app_dirs, get_i18n_dir, get_log_dir
from mym.infrastructure.resource_check import check_resources
from mym.ui.main_window import MainWindow
from mym.ui.theme.theme_manager import ThemeManager, ThemeMode

logger = logging.getLogger(__name__)


def setup_exception_handler(log_dir: Path) -> None:
    """Install global exception hook to log uncaught exceptions."""

    def exception_hook(exc_type: type, exc_value: BaseException, exc_tb: object) -> None:
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_log = log_dir / "crash.log"
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"{'=' * 60}\n")
            f.write(tb_str)
            f.write(f"{'=' * 60}\n")
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = exception_hook


def main() -> int:
    """Application entry point. Returns exit code."""
    app = QApplication(sys.argv)
    app.setApplicationName("MYM")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("MYM")

    ensure_app_dirs()
    log_dir = get_log_dir()
    setup_logging()

    i18n_dir = get_i18n_dir()
    missing = check_resources(i18n_dir)
    if missing:
        logger.error("Missing resources detected. Application may not function correctly.")

    setup_exception_handler(log_dir)

    config = get_config()
    i18n = I18nManager(i18n_dir)
    locale = config.get("language/locale")
    if locale:
        i18n.set_locale(locale)
    set_i18n(i18n)

    theme = ThemeManager()
    theme_mode = config.get("theme/mode")
    try:
        theme.set_mode(ThemeMode(theme_mode))
    except ValueError:
        theme.set_mode(ThemeMode.LIGHT)

    window = MainWindow(config, i18n, theme)
    window.show()

    logger.info("Application started. Locale: %s, Theme: %s", i18n.current_locale, theme.mode.value)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
