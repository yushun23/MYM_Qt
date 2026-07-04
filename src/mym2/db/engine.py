"""SQLAlchemy 引擎工厂。

为 SQLite 连接自动设置 PRAGMA foreign_keys、busy_timeout、WAL 模式。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """在每个新 SQLite 连接上设置必需的 PRAGMA。"""
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')
    cursor.execute('PRAGMA busy_timeout = 5000')
    cursor.execute('PRAGMA journal_mode = WAL')
    cursor.close()


def create_mym2_engine(db_path: str | Path, *, echo: bool = False) -> Engine:
    """创建配置好 PRAGMA 的 SQLite 引擎。

    Args:
        db_path: 数据库文件路径。
        echo: 是否输出 SQL 日志。

    Returns:
        配置好的 SQLAlchemy Engine。
    """
    db_url = f'sqlite:///{db_path}'
    engine = create_engine(
        db_url,
        echo=echo,
        connect_args={'check_same_thread': False},
    )
    event.listen(engine, 'connect', _set_sqlite_pragmas)
    return engine
