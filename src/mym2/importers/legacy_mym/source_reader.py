"""旧 .mym 只读源读取器。

- 只能通过 SQLite URI `mode=ro` 打开旧文件
- 禁止写 SQL、VACUUM、PRAGMA 写操作
- 打开前后校验文件哈希确保未修改
- 支持 row_factory 以返回命名行
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger('mym2.importers.legacy_mym.source_reader')

# 禁止执行的 SQL 前缀（大小写不敏感）
_FORBIDDEN_SQL_PREFIXES: tuple[str, ...] = (
    'insert', 'update', 'delete', 'drop', 'alter', 'create',
    'vacuum', 'reindex', 'attach', 'detach',
)

# 禁止的 PRAGMA（仅允许只读 pragma）
_ALLOWED_PRAGMAS: frozenset[str] = frozenset({
    'table_info', 'table_xinfo', 'index_list', 'index_info', 'index_xinfo',
    'foreign_key_list', 'foreign_key_check', 'integrity_check', 'quick_check',
    'schema_version', 'user_version', 'application_id', 'data_version',
    'encoding', 'collation_list', 'compile_options', 'page_count', 'page_size',
    'freelist_count', 'journal_mode', 'database_list', 'function_list',
    'module_list', 'pragma_list',
})


class SourceReader:
    """旧 .mym 文件只读读取器。

    使用 sqlite3 原生库（非 SQLAlchemy），确保 mode=ro，
    并在所有 SQL 执行前做安全检查。
    """

    def __init__(self, file_path: str | Path) -> None:
        self._path = Path(file_path).resolve()
        self._conn: sqlite3.Connection | None = None
        self._file_hash_before: str | None = None
        self._file_hash_after: str | None = None

    # ── 属性 ──────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    @property
    def file_hash_before(self) -> str | None:
        return self._file_hash_before

    @property
    def file_hash_after(self) -> str | None:
        return self._file_hash_after

    @property
    def is_hash_unchanged(self) -> bool:
        if self._file_hash_before is None or self._file_hash_after is None:
            return False
        return self._file_hash_before == self._file_hash_after

    # ── 打开/关闭 ─────────────────────────────────────

    def open(self) -> None:
        """以只读模式打开 .mym 文件。

        Raises:
            FileNotFoundError: 文件不存在。
            ValueError: 文件不是有效 SQLite 数据库。
        """
        if not self._path.exists():
            raise FileNotFoundError(f'旧账套文件不存在: {self._path}')

        # 记录打开前哈希
        self._file_hash_before = self._compute_sha256()

        # 验证 SQLite 文件头
        self._validate_sqlite_header()

        # 只读 URI 打开
        uri = f'file:{self._path}?mode=ro'
        try:
            self._conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as e:
            raise ValueError(f'无法打开旧 SQLite 文件: {e}') from e

        # 设置 row_factory 以便按名称访问列
        self._conn.row_factory = sqlite3.Row

        # mode=ro URI 已保证只读，无需额外 authorizer

        logger.info('已只读打开: %s', self._path)

    def close(self) -> None:
        """关闭连接并验证文件哈希未变。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self._file_hash_after = self._compute_sha256()
        logger.info('已关闭: %s (hash unchanged=%s)', self._path, self.is_hash_unchanged)

    def __enter__(self) -> SourceReader:
        self.open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── 查询方法 ──────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """安全执行只读 SQL 查询。

        Args:
            sql: SQL 语句。
            params: 参数。

        Returns:
            sqlite3 Cursor。

        Raises:
            RuntimeError: 连接未打开。
            ValueError: SQL 不安全。
        """
        if self._conn is None:
            raise RuntimeError('SourceReader 未打开')
        self._validate_sql(sql)
        return self._conn.execute(sql, params)

    def fetch_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """执行查询并返回所有行。"""
        return self.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        """执行查询并返回第一行。"""
        return self.execute(sql, params).fetchone()

    def fetch_scalar(self, sql: str, params: tuple = ()) -> Any:
        """执行查询并返回第一行第一列。"""
        row = self.fetch_one(sql, params)
        return row[0] if row else None

    def get_tables(self) -> list[str]:
        """获取所有用户表名（排除 sqlite_*）。"""
        rows = self.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r['name'] for r in rows]

    def get_table_info(self, table_name: str) -> list[dict]:
        """获取表的列信息。"""
        rows = self.fetch_all(f'PRAGMA table_info("{table_name}")')
        return [dict(r) for r in rows]

    def get_row_count(self, table_name: str) -> int:
        """获取表行数。"""
        return self.fetch_scalar(f'SELECT COUNT(*) FROM "{table_name}"') or 0

    def check_integrity(self) -> list[str]:
        """运行 PRAGMA integrity_check。返回错误列表（空 = OK）。"""
        rows = self.fetch_all('PRAGMA integrity_check')
        # integrity_check 返回单行 "ok" 或错误列表
        results = [r[0] for r in rows]
        if len(results) == 1 and results[0].lower() == 'ok':
            return []
        return results

    def check_foreign_keys(self) -> list[dict]:
        """运行 PRAGMA foreign_key_check。返回违规列表。"""
        rows = self.fetch_all('PRAGMA foreign_key_check')
        return [dict(r) for r in rows]

    # ── 内部方法 ──────────────────────────────────────

    def _compute_sha256(self) -> str:
        """计算文件的 SHA-256 哈希。"""
        sha = hashlib.sha256()
        with open(self._path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha.update(chunk)
        return sha.hexdigest()

    def _validate_sqlite_header(self) -> None:
        """验证文件以 'SQLite format 3' 开头。"""
        try:
            with open(self._path, 'rb') as f:
                header = f.read(16)
        except OSError as e:
            raise ValueError(f'无法读取文件: {e}') from e

        if len(header) < 16:
            raise ValueError(f'文件过小 ({len(header)} bytes)，不是有效 SQLite 数据库')

        magic = header[:16]
        if magic != b'SQLite format 3\x00':
            raise ValueError(
                f'文件不是有效 SQLite 数据库（文件头: {magic[:8]!r}），'
                f'请确认文件为 .mym 格式'
            )

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """安全检查：拒绝写 SQL 和禁止的 PRAGMA。"""
        stripped = sql.strip().lower()
        if not stripped:
            return

        # 检查禁止的 SQL 前缀
        for prefix in _FORBIDDEN_SQL_PREFIXES:
            if stripped.startswith(prefix):
                raise ValueError(f'禁止执行写 SQL: {sql[:60]}')

        # 检查 PRAGMA
        if stripped.startswith('pragma'):
            pragma_name = stripped.split('(')[0].replace('pragma', '').strip()
            # 去掉引号
            pragma_name = pragma_name.strip('"').strip("'")
            if pragma_name not in _ALLOWED_PRAGMAS:
                raise ValueError(f'禁止执行此 PRAGMA: {pragma_name}')

