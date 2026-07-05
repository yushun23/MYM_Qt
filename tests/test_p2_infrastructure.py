"""P2 tests: path service, QSettings, i18n fallback, theme switching."""

import json
import tempfile
from pathlib import Path

import pytest

from mym.infrastructure.paths import app_paths


class TestAppPaths:
    """Tests for application path service."""

    def test_get_user_data_dir_returns_path(self) -> None:
        p = app_paths.get_user_data_dir()
        assert isinstance(p, Path)
        assert p.name == "mym"

    def test_get_ledger_dir(self) -> None:
        p = app_paths.get_ledger_dir()
        assert p.exists()
        assert p.is_dir()

    def test_get_backup_dir(self) -> None:
        p = app_paths.get_backup_dir()
        assert p.exists()

    def test_get_export_dir(self) -> None:
        p = app_paths.get_export_dir()
        assert p.exists()

    def test_get_temp_dir(self) -> None:
        p = app_paths.get_temp_dir()
        assert p.exists()

    def test_get_log_dir(self) -> None:
        p = app_paths.get_log_dir()
        assert p.exists()

    def test_ensure_app_dirs(self) -> None:
        dirs = app_paths.ensure_app_dirs()
        assert len(dirs) >= 5
        for d in dirs:
            assert d.exists()

    def test_get_assets_dir(self) -> None:
        p = app_paths.get_assets_dir()
        assert isinstance(p, Path)

    def test_get_i18n_dir(self) -> None:
        p = app_paths.get_i18n_dir()
        assert isinstance(p, Path)


class TestI18n:
    """Tests for I18nManager."""

    def test_load_translations(self) -> None:
        from mym.infrastructure.i18n import I18nManager

        i18n_dir = app_paths.get_i18n_dir()
        mgr = I18nManager(i18n_dir)
        assert "zh_CN" in mgr.available_locales
        assert "en" in mgr.available_locales
        assert mgr.current_locale == "zh_CN"

    def test_tr_returns_string(self) -> None:
        from mym.infrastructure.i18n import I18nManager

        mgr = I18nManager(app_paths.get_i18n_dir())
        result = mgr.tr("app.title")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tr_fallback_to_default(self) -> None:
        from mym.infrastructure.i18n import I18nManager

        mgr = I18nManager(app_paths.get_i18n_dir())
        result = mgr.tr("nonexistent.key", default="DEFAULT")
        assert result == "DEFAULT"

    def test_tr_fallback_to_key_when_no_default(self) -> None:
        from mym.infrastructure.i18n import I18nManager

        mgr = I18nManager(app_paths.get_i18n_dir())
        result = mgr.tr("nonexistent.key")
        assert result == "nonexistent.key"

    def test_switch_locale(self) -> None:
        from mym.infrastructure.i18n import I18nManager

        mgr = I18nManager(app_paths.get_i18n_dir())
        mgr.set_locale("en")
        assert mgr.current_locale == "en"
        # English title should differ
        en_title = mgr.tr("app.title")
        mgr.set_locale("zh_CN")
        zh_title = mgr.tr("app.title")
        assert en_title != zh_title

    def test_switch_invalid_locale_keeps_current(self) -> None:
        from mym.infrastructure.i18n import I18nManager

        mgr = I18nManager(app_paths.get_i18n_dir())
        mgr.set_locale("en")
        mgr.set_locale("xx_XX")
        assert mgr.current_locale == "en"


class TestTheme:
    """Tests for ThemeManager."""

    def test_default_mode_light(self) -> None:
        from mym.ui.theme.theme_manager import ThemeManager, ThemeMode

        mgr = ThemeManager()
        assert mgr.mode == ThemeMode.LIGHT

    def test_switch_to_dark(self) -> None:
        from mym.ui.theme.theme_manager import ThemeManager, ThemeMode

        mgr = ThemeManager()
        mgr.set_mode(ThemeMode.DARK)
        assert mgr.mode == ThemeMode.DARK

    def test_dark_colors_differ_from_light(self) -> None:
        from mym.ui.theme.theme_manager import ThemeManager, ThemeMode, ThemeColors

        mgr = ThemeManager()
        light_bg = mgr.colors.bg_primary
        mgr.set_mode(ThemeMode.DARK)
        assert mgr.colors.bg_primary != light_bg

    def test_build_stylesheet_returns_string(self) -> None:
        from mym.ui.theme.theme_manager import ThemeManager

        mgr = ThemeManager()
        sheet = mgr.build_stylesheet()
        assert isinstance(sheet, str)
        assert len(sheet) > 0
        assert "QMainWindow" in sheet

    def test_theme_changed_signal(self, qtbot) -> None:
        from mym.ui.theme.theme_manager import ThemeManager, ThemeMode

        mgr = ThemeManager()
        with qtbot.waitSignal(mgr.theme_changed, timeout=1000):
            mgr.set_mode(ThemeMode.DARK)
