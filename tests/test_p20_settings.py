"""Tests for P20 – SettingsService."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym.application.services.settings_service import SettingsService, SettingsProfile
from mym.infrastructure.app_config import AppConfig
from mym.infrastructure.database.db_manager import DatabaseManager


@pytest.fixture
def config():
    """Mock-like config that stores values in memory."""
    class MemConfig:
        def __init__(self):
            self._data = {
                "language/locale": "zh_CN",
                "theme/mode": "light",
                "window/width": "1200",
                "window/height": "800",
                "modules/plugins_enabled": "",
                "export/default_dir": "",
                "recent/ledgers": "",
            }
        def get(self, key, default=""):
            return self._data.get(key, default)
        def get_bool(self, key):
            val = self.get(key)
            if isinstance(val, bool):
                return val
            return str(val).lower() in ("true", "1", "yes")
        def get_int(self, key):
            try:
                return int(self.get(key))
            except (ValueError, TypeError):
                return 0
        def set(self, key, value):
            self._data[key] = str(value)
        def get_recent_ledgers(self):
            raw = self._data.get("recent/ledgers", "")
            return [p for p in raw.split("|") if p] if raw else []
    return MemConfig()


@pytest.fixture
def db_mgr():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        tmp_path = Path(f.name)
    tmp_path.unlink(missing_ok=True)
    mgr = DatabaseManager(tmp_path)
    mgr.create()
    yield mgr
    mgr.close()
    tmp_path.unlink(missing_ok=True)


@pytest.fixture
def session(db_mgr):
    s = db_mgr.new_session()
    yield s
    s.close()


class TestSettingsService:
    def test_user_settings_profile(self, config):
        svc = SettingsService(config)
        profile = svc.get_user_settings()
        assert profile.language == "zh_CN"
        assert profile.theme == "light"

    def test_set_language_and_theme(self, config):
        svc = SettingsService(config)
        svc.set_language("en")
        svc.set_theme("dark")
        assert config.get("language/locale") == "en"
        assert config.get("theme/mode") == "dark"


    def test_set_plugin_enabled(self, config):
        svc = SettingsService(config)
        svc.set_plugin_enabled("my_plugin", True)
        assert "my_plugin" in config.get("modules/plugins_enabled").split("|")
        svc.set_plugin_enabled("my_plugin", False)
        assert "my_plugin" not in config.get("modules/plugins_enabled").split("|")

    def test_ledger_settings(self, config, session):
        svc = SettingsService(config, session)
        svc.set_ledger_name("测试账本")
        svc.set_currency("USD")
        session.flush()

        assert svc.get_ledger_setting("ledger/name") == "测试账本"
        assert svc.get_ledger_setting("ledger/currency") == "USD"

    def test_auto_backup_settings(self, config, session):
        svc = SettingsService(config, session)
        svc.set_auto_backup(True, interval_days=3, max_count=5)
        session.flush()

        assert svc.get_ledger_setting_bool("backup/enabled") is True
        assert svc.get_ledger_setting("backup/interval_days") == "3"
        assert svc.get_ledger_setting("backup/max_count") == "5"

    def test_proxy_settings(self, config, session):
        svc = SettingsService(config, session)
        svc.set_proxy(True, "192.168.1.1", 3128, "https")
        session.flush()

        assert svc.get_ledger_setting_bool("proxy/enabled") is True
        assert svc.get_ledger_setting("proxy/host") == "192.168.1.1"
        assert svc.get_ledger_setting("proxy/port") == "3128"
        assert svc.get_ledger_setting("proxy/type") == "https"

    def test_ai_config(self, config, session):
        svc = SettingsService(config, session)
        svc.set_ai_config("openai", "gpt-4", "https://api.openai.com/v1", 60)
        session.flush()

        assert svc.get_ledger_setting("ai/provider") == "openai"
        assert svc.get_ledger_setting("ai/model") == "gpt-4"
        assert svc.get_ledger_setting("ai/timeout") == "60"

    def test_get_all_ledger_settings(self, config, session):
        svc = SettingsService(config, session)
        svc.set_ledger_name("my_ledger")
        svc.set_currency("CNY")
        session.flush()

        all_settings = svc.get_all_ledger_settings()
        assert all_settings["ledger/name"] == "my_ledger"
        assert all_settings["ledger/currency"] == "CNY"

    def test_health_report_no_session(self, config):
        svc = SettingsService(config)
        report = svc.get_health_report()
        assert report["status"] == "no_session"

    def test_health_report_with_session(self, config, session):
        svc = SettingsService(config, session)
        report = svc.get_health_report()
        assert report["status"] in ("healthy", "issues_found")
        assert "accounts" in report
        assert "transactions" in report
