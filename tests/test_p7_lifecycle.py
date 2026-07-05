"""P7 tests: Backup, restore, password, ledger lifecycle."""

import tempfile
from pathlib import Path

import pytest

from mym.application.services.backup_service import BackupService
from mym.application.services.ledger_lifecycle import LedgerLifecycle
from mym.application.services.password_service import PasswordService
from mym.infrastructure.database.db_manager import DatabaseManager


def test_password_hash_and_verify():
    password = "test123"
    h, s = PasswordService.hash_password(password)
    assert PasswordService.verify(password, h, s)
    assert not PasswordService.verify("wrong", h, s)
    assert PasswordService.has_password(h)
    assert not PasswordService.has_password(None)


def test_backup_and_restore():
    with tempfile.TemporaryDirectory() as backup_dir:
        backup_dir_path = Path(backup_dir)
        svc = BackupService(backup_dir_path)

        # Create a test file
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            test_path = Path(f.name)
        test_path.unlink(missing_ok=True)

        # Create a ledger
        mgr = DatabaseManager(test_path)
        mgr.create()
        mgr.close()

        # Backup
        backup_path = svc.backup(test_path)
        assert backup_path.exists()

        # Restore
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f2:
            target = Path(f2.name)
        target.unlink(missing_ok=True)
        svc.restore(backup_path, target)
        assert target.exists()

        target.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
        test_path.unlink(missing_ok=True)


def test_backup_list():
    with tempfile.TemporaryDirectory() as backup_dir:
        svc = BackupService(Path(backup_dir))
        backups = svc.list_backups()
        assert isinstance(backups, list)


def test_ledger_create_and_open():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        ledger_path = Path(f.name)
    ledger_path.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory() as backup_dir:
        lifecycle = LedgerLifecycle(Path(backup_dir))
        try:
            mgr = lifecycle.create(ledger_path, auto_backup=False)
            assert lifecycle.is_open
            lifecycle.close(backup=False)

            # Re-open
            mgr2 = lifecycle.open(ledger_path)
            assert lifecycle.is_open
            lifecycle.close(backup=False)
        finally:
            ledger_path.unlink(missing_ok=True)


def test_password_protected_ledger():
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        ledger_path = Path(f.name)
    ledger_path.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory() as backup_dir:
        lifecycle = LedgerLifecycle(Path(backup_dir))
        try:
            mgr = lifecycle.create(ledger_path, password="secret", auto_backup=False)
            lifecycle.close(backup=False)

            # Open with wrong password
            with pytest.raises(ValueError):
                lifecycle.open(ledger_path, password="wrong")

            # Open with correct password
            lifecycle.open(ledger_path, password="secret")
            assert lifecycle.is_open
            lifecycle.close(backup=False)
        finally:
            ledger_path.unlink(missing_ok=True)
