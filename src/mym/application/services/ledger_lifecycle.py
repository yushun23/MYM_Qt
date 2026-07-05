"""Ledger lifecycle management: create, open, close, auto-backup."""

import logging
from pathlib import Path

from mym.application.services.backup_service import BackupService
from mym.application.services.password_service import PasswordService
from mym.infrastructure.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)


class LedgerLifecycle:
    """Manages the full lifecycle of a ledger: create, open, close, backup."""

    def __init__(self, backup_dir: Path) -> None:
        self._backup_service = BackupService(backup_dir)
        self._db_manager: DatabaseManager | None = None

    @property
    def db_manager(self) -> DatabaseManager:
        if self._db_manager is None:
            raise RuntimeError("No ledger open.")
        return self._db_manager

    @property
    def is_open(self) -> bool:
        return self._db_manager is not None

    @property
    def ledger_path(self) -> Path | None:
        if self._db_manager:
            return self._db_manager.ledger_path
        return None

    def create(
        self,
        path: Path,
        password: str | None = None,
        auto_backup: bool = True,
    ) -> DatabaseManager:
        """Create a new ledger."""
        mgr = DatabaseManager(path)
        mgr.create()

        if password:
            self._set_password(mgr, password)

        if auto_backup:
            self._backup_service.backup(path)

        self._db_manager = mgr
        logger.info("Ledger created: %s", path)
        return mgr

    def open(self, path: Path, password: str | None = None) -> DatabaseManager:
        """Open an existing ledger, optionally verifying password."""
        mgr = DatabaseManager(path)
        mgr.open()

        if password is not None and not self._verify_password(mgr, password):
            mgr.close()
            raise ValueError("Password incorrect")

        self._db_manager = mgr
        logger.info("Ledger opened: %s", path)
        return mgr

    def close(self, *, backup: bool = True) -> None:
        """Close the current ledger, optionally creating a backup."""
        if self._db_manager:
            if backup:
                self._backup_service.backup(self._db_manager.ledger_path)
            self._db_manager.close()
            logger.info("Ledger closed: %s", self._db_manager.ledger_path)
            self._db_manager = None

    def check_password(self, password: str) -> bool:
        """Check if the given password matches the ledger's stored password."""
        if not self._db_manager:
            raise RuntimeError("No ledger open.")
        return self._verify_password(self._db_manager, password)

    def set_password(self, new_password: str) -> None:
        """Set or change the ledger password."""
        if not self._db_manager:
            raise RuntimeError("No ledger open.")
        self._set_password(self._db_manager, new_password)

    def remove_password(self) -> None:
        """Remove the ledger password."""
        if not self._db_manager:
            raise RuntimeError("No ledger open.")
        session = self._db_manager.new_session()
        try:
            from mym.domain.entities.setting import AppSetting
            from sqlalchemy import select
            stmt = select(AppSetting).where(AppSetting.key == "ledger_password_hash")
            setting = session.execute(stmt).scalar_one_or_none()
            if setting:
                session.delete(setting)
            stmt2 = select(AppSetting).where(AppSetting.key == "ledger_password_salt")
            setting2 = session.execute(stmt2).scalar_one_or_none()
            if setting2:
                session.delete(setting2)
            session.commit()
            logger.info("Password removed")
        finally:
            session.close()

    def _set_password(self, mgr: DatabaseManager, password: str) -> None:
        hash_val, salt = PasswordService.hash_password(password)
        session = mgr.new_session()
        try:
            from mym.domain.entities.setting import AppSetting
            h = AppSetting(key="ledger_password_hash", value=hash_val, description="Password hash")
            s = AppSetting(key="ledger_password_salt", value=salt, description="Password salt")
            session.add(h)
            session.add(s)
            session.commit()
        finally:
            session.close()

    def _verify_password(self, mgr: DatabaseManager, password: str) -> bool:
        session = mgr.new_session()
        try:
            from mym.domain.entities.setting import AppSetting
            from sqlalchemy import select
            stmt = select(AppSetting).where(AppSetting.key == "ledger_password_hash")
            hash_setting = session.execute(stmt).scalar_one_or_none()
            if not hash_setting:
                return True  # No password set
            stmt2 = select(AppSetting).where(AppSetting.key == "ledger_password_salt")
            salt_setting = session.execute(stmt2).scalar_one_or_none()
            if not salt_setting:
                return True
            return PasswordService.verify(password, hash_setting.value, salt_setting.value)
        finally:
            session.close()
