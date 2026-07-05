"""SettingsService – manages user-level and ledger-level settings."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from mym.domain.entities.setting import AppSetting
from mym.infrastructure.app_config import AppConfig, get_config
from mym.infrastructure.database.health import check_health as db_health_check

logger = logging.getLogger(__name__)


@dataclass
class SettingsProfile:
    """Combined user and ledger settings profile."""

    # User-level (from QSettings)
    language: str = "zh_CN"
    theme: str = "light"
    font_family: str = ""
    font_size: int = 12
    window_width: int = 1200
    window_height: int = 800
    recent_ledgers: list[str] = field(default_factory=list)
    export_dir: str = ""
    show_stock: bool = False
    plugins_enabled: list[str] = field(default_factory=list)

    # Ledger-level (from database)
    ledger_name: str = ""
    currency: str = "CNY"
    auto_backup_enabled: bool = True
    auto_backup_interval_days: int = 7
    max_backup_count: int = 10
    proxy_enabled: bool = False
    proxy_host: str = ""
    proxy_port: int = 8080
    proxy_type: str = "http"
    ai_provider: str = ""
    ai_model: str = ""
    ai_base_url: str = ""
    ai_timeout: int = 30

    @classmethod
    def from_config(cls, config: AppConfig) -> "SettingsProfile":
        return cls(
            language=config.get("language/locale"),
            theme=config.get("theme/mode"),
            font_family=config.get("font/family"),
            font_size=config.get_int("font/size"),
            window_width=config.get_int("window/width"),
            window_height=config.get_int("window/height"),
            recent_ledgers=config.get_recent_ledgers(),
            export_dir=config.get("export/default_dir"),
            show_stock=config.get_bool("modules/show_stock"),
            plugins_enabled=[
                p for p in config.get("modules/plugins_enabled", "").split("|") if p
            ],
        )


class SettingsService:
    """Service for reading and writing settings across user and ledger scopes."""

    def __init__(self, config: AppConfig | None = None, session: Session | None = None) -> None:
        self._config = config or get_config()
        self._session = session

    # --- User-Level Settings ---

    def get_user_settings(self) -> SettingsProfile:
        return SettingsProfile.from_config(self._config)

    def set_language(self, locale: str) -> None:
        self._config.set("language/locale", locale)

    def set_theme(self, mode: str) -> None:
        self._config.set("theme/mode", mode)

    def set_font(self, family: str, size: int) -> None:
        self._config.set("font/family", family)
        self._config.set("font/size", size)

    def set_export_dir(self, path: str) -> None:
        self._config.set("export/default_dir", path)

    def set_stock_visibility(self, visible: bool) -> None:
        self._config.set("modules/show_stock", visible)

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        current = [
            p for p in self._config.get("modules/plugins_enabled", "").split("|") if p
        ]
        if enabled and plugin_id not in current:
            current.append(plugin_id)
        elif not enabled and plugin_id in current:
            current.remove(plugin_id)
        self._config.set("modules/plugins_enabled", "|".join(current))

    # --- Ledger-Level Settings ---

    def _get_ledger_setting(self, key: str) -> str | None:
        if not self._session:
            return None
        stmt = self._session.query(AppSetting).where(AppSetting.key == key)
        setting = stmt.first()
        return setting.value if setting else None

    def _set_ledger_setting(self, key: str, value: str | None, description: str = "") -> None:
        if not self._session:
            return
        stmt = self._session.query(AppSetting).where(AppSetting.key == key)
        setting = stmt.first()
        if setting:
            setting.value = value
        else:
            setting = AppSetting(key=key, value=value, description=description)
            self._session.add(setting)

    def get_ledger_setting(self, key: str, default: str = "") -> str:
        val = self._get_ledger_setting(key)
        return val if val is not None else default

    def get_ledger_setting_bool(self, key: str, default: bool = False) -> bool:
        val = self._get_ledger_setting(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    def set_ledger_name(self, name: str) -> None:
        self._set_ledger_setting("ledger/name", name, "账套名称")

    def set_currency(self, currency: str) -> None:
        self._set_ledger_setting("ledger/currency", currency, "默认币种")

    def set_auto_backup(self, enabled: bool, interval_days: int = 7, max_count: int = 10) -> None:
        self._set_ledger_setting("backup/enabled", str(enabled), "自动备份开关")
        self._set_ledger_setting("backup/interval_days", str(interval_days), "备份间隔天数")
        self._set_ledger_setting("backup/max_count", str(max_count), "最大备份数量")

    def set_proxy(self, enabled: bool, host: str = "",
                   port: int = 8080, proxy_type: str = "http") -> None:
        self._set_ledger_setting("proxy/enabled", str(enabled))
        self._set_ledger_setting("proxy/host", host)
        self._set_ledger_setting("proxy/port", str(port))
        self._set_ledger_setting("proxy/type", proxy_type)
        logger.info("Proxy settings updated (credentials not logged)")

    def set_ai_config(self, provider: str, model: str, base_url: str, timeout: int = 30) -> None:
        self._set_ledger_setting("ai/provider", provider, "AI提供商")
        self._set_ledger_setting("ai/model", model, "AI模型")
        self._set_ledger_setting("ai/base_url", base_url, "AI接口地址")
        self._set_ledger_setting("ai/timeout", str(timeout), "AI超时时间")

    def get_all_ledger_settings(self) -> dict[str, str]:
        if not self._session:
            return {}
        settings = self._session.query(AppSetting).all()
        return {s.key: s.value for s in settings if s.value is not None}

    def get_health_report(self) -> dict:
        if not self._session:
            return {"status": "no_session", "issues": []}
        try:
            report = db_health_check(self._session)
            from sqlalchemy import select, func
            from mym.domain.entities.account import Account
            from mym.domain.entities.transaction import Transaction
            acct_count = self._session.execute(
                select(func.count(Account.id))
            ).scalar() or 0
            tx_count = self._session.execute(
                select(func.count(Transaction.id))
            ).scalar() or 0
            return {
                "status": "healthy" if report.is_healthy else "issues_found",
                "integrated": report.integrity_ok,
                "foreign_keys": report.foreign_keys_ok,
                "accounts": acct_count,
                "transactions": tx_count,
                "issues": report.issues,
            }
        except Exception as e:
            logger.exception("Health check failed")
            return {"status": "error", "issues": [str(e)]}
