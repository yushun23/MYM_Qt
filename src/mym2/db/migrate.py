"""Alembic 迁移执行封装。

提供在应用启动时自动运行 `alembic upgrade head` 的能力。
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command

logger = logging.getLogger('mym2.db.migrate')

_ALEMBIC_INI: str | None = None
_INITIAL_REVISION = '81c53c9ecdc7'


def set_alembic_ini_path(path: str) -> None:
    """设置 alembic.ini 路径（测试覆写用）。"""
    global _ALEMBIC_INI
    _ALEMBIC_INI = path


def _get_alembic_cfg(db_url: str) -> Config:
    """获取 Alembic 配置。"""
    ini_path = _ALEMBIC_INI
    if ini_path is None:
        # 默认：项目根目录下的 alembic.ini
        ini_path = str(Path(__file__).resolve().parent.parent.parent.parent / 'alembic.ini')
    cfg = Config(ini_path)
    cfg.set_main_option('sqlalchemy.url', db_url)
    return cfg


def upgrade_to_head(db_path: str | Path) -> None:
    """将数据库升级到最新版本。

    在应用启动时调用，确保 schema 与代码一致。

    Args:
        db_path: 数据库文件路径。
    """
    db_path = Path(db_path)
    _repair_empty_sqlite_revision(db_path)
    db_url = f'sqlite:///{db_path}'
    cfg = _get_alembic_cfg(db_url)
    logger.info('正在升级数据库到最新版本...')
    command.upgrade(cfg, 'head')
    logger.info('数据库升级完成')


def _repair_empty_sqlite_revision(db_path: Path) -> None:
    """修复早期已建初始表但 alembic_version 为空的 SQLite 库。"""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return
    try:
        with db_path.open('rb') as fh:
            if fh.read(16) != b'SQLite format 3\x00':
                return
    except OSError:
        return

    conn = sqlite3.connect(str(db_path))
    try:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {str(row[0]) for row in table_rows}
        if 'transactions' not in tables or 'accounts' not in tables:
            return
        if 'alembic_version' not in tables:
            conn.execute(
                'CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)'
            )
        versions = conn.execute('SELECT version_num FROM alembic_version').fetchall()
        if versions:
            return
        conn.execute('DELETE FROM alembic_version')
        conn.execute(
            'INSERT INTO alembic_version (version_num) VALUES (?)',
            (_INITIAL_REVISION,),
        )
        conn.commit()
        logger.warning('已修复空 Alembic 版本表，标记为初始版本')
    finally:
        conn.close()
