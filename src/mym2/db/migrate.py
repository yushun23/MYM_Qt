"""Alembic 迁移执行封装。

提供在应用启动时自动运行 `alembic upgrade head` 的能力。
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command

logger = logging.getLogger('mym2.db.migrate')

_ALEMBIC_INI: str | None = None


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
    db_url = f'sqlite:///{db_path}'
    cfg = _get_alembic_cfg(db_url)
    logger.info('正在升级数据库到最新版本...')
    command.upgrade(cfg, 'head')
    logger.info('数据库升级完成')
