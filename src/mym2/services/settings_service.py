"""应用偏好服务。

app_settings 只保存非秘密偏好。API key、密码、token、旧 password_hash
等秘密必须经由 keyring 或本次会话内存处理，不能落入此服务。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym2.db.models.app_setting import AppSetting

SECRET_KEY_PARTS: tuple[str, ...] = (
    'api',
    'auth',
    'credential',
    'hash',
    'key',
    'license',
    'password',
    'secret',
    'session',
    'token',
)

ALLOWED_SETTING_KEYS: frozenset[str] = frozenset({
    'ai_enabled',
    'ai_model',
    'ai_service_url',
    'backup_auto_before_migration',
    'backup_retention_count',
    'backup_schedule',
    'export_dir',
    'font_size',
    'language',
    'theme',
})

DEFAULT_SETTINGS: dict[str, str] = {
    'theme': 'dark',
    'language': 'zh_CN',
    'font_size': '11',
    'export_dir': '',
    'backup_retention_count': '10',
    'backup_auto_before_migration': 'true',
    'backup_schedule': 'manual',
    'ai_enabled': 'false',
    'ai_model': '',
    'ai_service_url': '',
}


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    """备份策略偏好。"""

    retention_count: int = 10
    auto_before_migration: bool = True
    schedule: str = 'manual'


class SettingsService:
    """读写 app_settings 的服务层入口。"""

    def get(self, session: Session, key: str, default: str | None = None) -> str | None:
        """读取一个非秘密偏好。"""
        self._validate_key(key)
        setting = session.scalars(
            select(AppSetting).where(AppSetting.key == key)
        ).first()
        if setting is None:
            return DEFAULT_SETTINGS.get(key, default)
        return setting.value

    def set(self, session: Session, key: str, value: str) -> AppSetting:
        """保存一个非秘密偏好。"""
        self._validate_key(key)
        value = str(value)
        setting = session.scalars(
            select(AppSetting).where(AppSetting.key == key)
        ).first()
        if setting is None:
            setting = AppSetting(id=str(uuid.uuid4()), key=key, value=value)
            session.add(setting)
        else:
            setting.value = value
        session.flush()
        return setting

    def set_many(self, session: Session, values: dict[str, str]) -> None:
        """批量保存非秘密偏好。"""
        for key, value in values.items():
            self.set(session, key, value)

    def get_bool(self, session: Session, key: str, default: bool = False) -> bool:
        """读取 bool 偏好。"""
        raw = self.get(session, key, 'true' if default else 'false')
        return str(raw).strip().lower() in {'1', 'true', 'yes', 'on'}

    def get_int(self, session: Session, key: str, default: int = 0) -> int:
        """读取 int 偏好。"""
        raw = self.get(session, key, str(default))
        try:
            return int(str(raw))
        except ValueError:
            return default

    def get_backup_policy(self, session: Session) -> BackupPolicy:
        """读取备份策略。"""
        retention = self.get_int(session, 'backup_retention_count', 10)
        retention = max(1, min(retention, 365))
        return BackupPolicy(
            retention_count=retention,
            auto_before_migration=self.get_bool(
                session, 'backup_auto_before_migration', True
            ),
            schedule=self.get(session, 'backup_schedule', 'manual') or 'manual',
        )

    @staticmethod
    def _validate_key(key: str) -> None:
        cleaned = key.strip().lower()
        if cleaned != key:
            raise ValueError('设置键必须使用规范小写名称')
        if cleaned not in ALLOWED_SETTING_KEYS:
            raise ValueError(f'不允许保存的设置键: {key}')
        if any(part in cleaned for part in SECRET_KEY_PARTS):
            raise ValueError(f'设置键疑似秘密，禁止保存到 app_settings: {key}')
