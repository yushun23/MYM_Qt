"""MYM Application entry point."""

import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMenuBar,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from mym.infrastructure.app_config import AppConfig, get_config
from mym.infrastructure.i18n import I18nManager, set_i18n, tr
from mym.infrastructure.logging_config.logger import setup_logging
from mym.infrastructure.paths.app_paths import ensure_app_dirs, get_i18n_dir, get_log_dir
from mym.infrastructure.resource_check import check_resources
from mym.ui.theme.theme_manager import ThemeManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, config: AppConfig, i18n: I18nManager, theme: ThemeManager) -> None:
        super().__init__()
        self._config = config
        self._i18n = i18n
        self._theme = theme

        self.setWindowTitle(i18n.tr("app.title"))
        self._restore_window_state()
        self._apply_theme()
        self._setup_menu_bar()
        self._setup_status_bar()
        self._setup_central_widget()

        # Connect signals
        self._theme.theme_changed.connect(self._on_theme_changed)

    def _restore_window_state(self) -> None:
        w = self._config.get_int("window/width")
        h = self._config.get_int("window/height")
        self.resize(w, h)
        if self._config.get_bool("window/maximized"):
            self.showMaximized()

    def _apply_theme(self) -> None:
        self.setStyleSheet(self._theme.build_stylesheet())

    def _on_theme_changed(self, colors: object) -> None:
        self._apply_theme()

    def _setup_menu_bar(self) -> None:
        menubar = self.menuBar()
        t = self._i18n.tr

        file_menu = menubar.addMenu(t("menu.file"))
        file_menu.addAction(t("menu.file.new"))
        file_menu.addAction(t("menu.file.open"))
        file_menu.addSeparator()
        exit_action = QAction(t("menu.file.exit"), self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu(t("menu.view"))
        view_menu.addAction(t("menu.view.dashboard"))
        view_menu.addAction(t("menu.view.record"))

        help_menu = menubar.addMenu(t("menu.help"))
        help_menu.addAction(t("menu.help.about"))

    def _setup_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(self._i18n.tr("app.ready"))

    def _setup_central_widget(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        placeholder = QLabel(self._i18n.tr("welcome.text"))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(24)
        placeholder.setFont(font)
        layout.addWidget(placeholder)
        self.setCentralWidget(central)

    def closeEvent(self, event: object) -> None:
        """Save window state on close."""
        self._config.save_window_state(
            self.width(), self.height(), self.isMaximized()
        )
        super().closeEvent(event)


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

    # Ensure all directories exist
    ensure_app_dirs()

    # Setup logging
    log_dir = get_log_dir()
    setup_logging()

    # Check resources
    i18n_dir = get_i18n_dir()
    missing = check_resources(i18n_dir)
    if missing:
        logger.error("Missing resources detected. Application may not function correctly.")

    # Exception handler
    setup_exception_handler(log_dir)

    # Initialize services
    config = get_config()
    i18n = I18nManager(i18n_dir)
    locale = config.get("language/locale")
    if locale:
        i18n.set_locale(locale)
    set_i18n(i18n)

    theme = ThemeManager()
    theme_mode = config.get("theme/mode")
    from mym.ui.theme.theme_manager import ThemeMode

    try:
        theme.set_mode(ThemeMode(theme_mode))
    except ValueError:
        theme.set_mode(ThemeMode.LIGHT)

    # Create and show main window
    window = MainWindow(config, i18n, theme)
    window.show()

    logger.info("Application started. Locale: %s, Theme: %s", i18n.current_locale, theme.mode.value)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
