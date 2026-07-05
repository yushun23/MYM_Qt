"""Smoke test: verify QApplication and MainWindow can be created and closed."""

import pytest
from mym.infrastructure.app_config import AppConfig
from mym.infrastructure.i18n import I18nManager, set_i18n
from mym.infrastructure.paths.app_paths import get_i18n_dir
from mym.ui.theme.theme_manager import ThemeManager


@pytest.fixture(scope="session")
def i18n_mgr() -> I18nManager:
    mgr = I18nManager(get_i18n_dir())
    set_i18n(mgr)
    return mgr


def test_qapp_exists(qapp: object) -> None:
    """Verify QApplication can be created (pytest-qt provides qapp fixture)."""
    assert qapp is not None


def test_main_window_creation(qapp: object, i18n_mgr: I18nManager) -> None:
    """Verify MainWindow can be created and closed."""
    from mym.app import MainWindow

    config = AppConfig()
    theme = ThemeManager()
    window = MainWindow(config, i18n_mgr, theme)
    assert window is not None
    assert "MYM" in window.windowTitle()
    window.close()
    window.deleteLater()


def test_main_window_menu(qapp: object, i18n_mgr: I18nManager) -> None:
    """Verify MainWindow has menu bar with expected menus."""
    from mym.app import MainWindow

    config = AppConfig()
    theme = ThemeManager()
    window = MainWindow(config, i18n_mgr, theme)
    menubar = window.menuBar()
    actions = [a.text() for a in menubar.actions()]
    assert any("文件" in a or "File" in a for a in actions)
    assert any("视图" in a or "View" in a for a in actions)
    assert any("帮助" in a or "Help" in a for a in actions)
    window.close()
    window.deleteLater()
