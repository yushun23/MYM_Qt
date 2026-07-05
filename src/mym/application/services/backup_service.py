"""Backup and restore service for ledger files."""

import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupService:
    """Handles backup and restore of ledger SQLite files."""

    def __init__(self, backup_dir: Path) -> None:
        self._backup_dir = backup_dir
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def backup(self, ledger_path: Path) -> Path:
        """Create a timestamped backup of the ledger file.

        Returns the path to the backup file.
        """
        if not ledger_path.exists():
            raise FileNotFoundError(f"Ledger not found: {ledger_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{ledger_path.stem}_{timestamp}.bak"
        backup_path = self._backup_dir / backup_name

        shutil.copy2(ledger_path, backup_path)
        logger.info("Backup created: %s", backup_path)
        return backup_path

    def restore(self, backup_path: Path, target_path: Path) -> None:
        """Restore a backup to the target ledger path.

        Creates a backup of the current ledger before overwriting.
        """
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        if target_path.exists():
            # Backup current before restore
            self.backup(target_path)

        shutil.copy2(backup_path, target_path)
        logger.info("Restored from %s to %s", backup_path, target_path)

    def list_backups(self, prefix: str = "") -> list[Path]:
        """List backup files, optionally filtered by prefix."""
        backups = sorted(
            self._backup_dir.glob("*.bak"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if prefix:
            backups = [b for b in backups if b.name.startswith(prefix)]
        return backups

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """Remove old backups, keeping the most recent `keep_count`."""
        backups = self.list_backups()
        if len(backups) <= keep_count:
            return 0
        removed = 0
        for old in backups[keep_count:]:
            old.unlink()
            removed += 1
            logger.info("Removed old backup: %s", old)
        return removed
