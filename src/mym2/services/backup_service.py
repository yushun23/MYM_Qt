"""SQLite 数据库备份与恢复服务。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from mym2.db.session import reset_session_factory

RESTORE_CONFIRMATION = 'RESTORE MYM2 DATA'
MANIFEST_NAME = 'backup_manifest.json'


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    """备份元数据。"""

    filename: str
    sha256: str
    created_at: str
    reason: str
    size_bytes: int
    retention_count: int


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """恢复结果。"""

    backup_sha256: str
    restored_at: str
    restart_required: bool = True


class BackupVerificationError(ValueError):
    """备份验证失败。"""


class BackupService:
    """使用 SQLite backup API 备份和恢复数据库。"""

    def create_backup(
        self,
        db_path: str | Path,
        backup_dir: str | Path,
        *,
        reason: str = 'manual',
        retention_count: int = 10,
    ) -> BackupMetadata:
        """创建备份并写入 manifest。

        Args:
            db_path: 源 SQLite 数据库。
            backup_dir: 备份目录。
            reason: manual / before_migration 等原因。
            retention_count: 保留最近 N 个备份。
        """
        db_path = Path(db_path)
        backup_dir = Path(backup_dir)
        if not db_path.exists():
            raise FileNotFoundError(f'数据库不存在: {db_path}')
        backup_dir.mkdir(parents=True, exist_ok=True)
        if db_path.stat().st_size == 0:
            self._initialize_empty_sqlite(db_path)

        retention_count = max(1, retention_count)
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        stamp = datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')
        backup_path = backup_dir / f'mym2_{reason}_{stamp}.db'

        self._sqlite_backup(db_path, backup_path)
        self.verify_backup(backup_path)

        metadata = BackupMetadata(
            filename=backup_path.name,
            sha256=self.sha256_file(backup_path),
            created_at=created_at,
            reason=reason,
            size_bytes=backup_path.stat().st_size,
            retention_count=retention_count,
        )
        self._append_manifest(backup_dir, metadata)
        self._apply_retention(backup_dir, retention_count)
        return metadata

    def verify_backup(
        self,
        backup_path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> str:
        """验证备份文件为完整 SQLite，并可选校验 SHA-256。"""
        backup_path = Path(backup_path)
        if not backup_path.exists():
            raise BackupVerificationError(f'备份不存在: {backup_path}')
        actual_sha256 = self.sha256_file(backup_path)
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise BackupVerificationError('备份 SHA-256 校验失败')

        try:
            conn = sqlite3.connect(f'{backup_path.resolve().as_uri()}?mode=ro', uri=True)
            try:
                integrity = conn.execute('PRAGMA integrity_check').fetchone()
                if not integrity or str(integrity[0]).lower() != 'ok':
                    raise BackupVerificationError('备份完整性检查失败')
                foreign_keys = conn.execute('PRAGMA foreign_key_check').fetchall()
                if foreign_keys:
                    raise BackupVerificationError('备份外键检查失败')
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise BackupVerificationError(f'备份不是有效 SQLite: {exc}') from exc

        return actual_sha256

    def restore_backup(
        self,
        backup_path: str | Path,
        target_db_path: str | Path,
        *,
        expected_sha256: str | None = None,
        confirmation_text: str,
    ) -> RestoreResult:
        """验证并恢复备份。

        恢复会先关闭全局 Session 工厂，复制到临时文件并验证，再原子替换目标库。
        调用方应在返回后提示用户重启应用。
        """
        if confirmation_text != RESTORE_CONFIRMATION:
            raise PermissionError('恢复需要显式确认文本')

        backup_path = Path(backup_path)
        target_db_path = Path(target_db_path)
        backup_sha256 = self.verify_backup(
            backup_path, expected_sha256=expected_sha256
        )

        reset_session_factory()
        target_db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_restore = target_db_path.with_suffix(target_db_path.suffix + '.restore_tmp')
        if temp_restore.exists():
            temp_restore.unlink()

        self._sqlite_backup(backup_path, temp_restore)
        self.verify_backup(temp_restore, expected_sha256=backup_sha256)

        for suffix in ('-wal', '-shm'):
            sidecar = Path(str(target_db_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(temp_restore, target_db_path)

        return RestoreResult(
            backup_sha256=backup_sha256,
            restored_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            restart_required=True,
        )

    @staticmethod
    def sha256_file(path: str | Path) -> str:
        """计算文件 SHA-256。"""
        h = hashlib.sha256()
        with Path(path).open('rb') as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def metadata_path(backup_dir: str | Path) -> Path:
        """返回 manifest 路径。"""
        return Path(backup_dir) / MANIFEST_NAME

    def load_manifest(self, backup_dir: str | Path) -> list[BackupMetadata]:
        """读取 manifest。"""
        path = self.metadata_path(backup_dir)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding='utf-8'))
        return [BackupMetadata(**item) for item in data.get('backups', [])]

    def _append_manifest(
        self, backup_dir: Path, metadata: BackupMetadata
    ) -> None:
        entries = self.load_manifest(backup_dir)
        entries.append(metadata)
        self._write_manifest(backup_dir, entries)

    def _apply_retention(self, backup_dir: Path, retention_count: int) -> None:
        entries = sorted(
            self.load_manifest(backup_dir), key=lambda item: item.created_at
        )
        keep = entries[-retention_count:]
        remove = entries[:-retention_count]
        for item in remove:
            old_path = backup_dir / item.filename
            if old_path.exists():
                old_path.unlink()
        self._write_manifest(backup_dir, keep)

    def _write_manifest(
        self, backup_dir: Path, entries: list[BackupMetadata]
    ) -> None:
        path = self.metadata_path(backup_dir)
        payload = {'backups': [asdict(item) for item in entries]}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding='utf-8',
        )

    @staticmethod
    def _sqlite_backup(source_path: Path, target_path: Path) -> None:
        source = sqlite3.connect(f'{source_path.resolve().as_uri()}?mode=ro', uri=True)
        try:
            target = sqlite3.connect(str(target_path))
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

    @staticmethod
    def _initialize_empty_sqlite(db_path: Path) -> None:
        """将空占位文件初始化为有效 SQLite，便于备份测试/首次导入。"""
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS __mym2_empty_backup_marker (id INTEGER)')
            conn.execute('DROP TABLE IF EXISTS __mym2_empty_backup_marker')
            conn.commit()
        finally:
            conn.close()
