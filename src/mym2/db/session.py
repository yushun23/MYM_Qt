"""SQLAlchemy Session 管理。

提供线程安全的 scoped_session 工厂。
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

_SessionFactory: scoped_session[Session] | None = None


def init_session_factory(engine: Engine) -> scoped_session[Session]:
    """初始化全局 Session 工厂（线程安全）。

    Args:
        engine: SQLAlchemy Engine。

    Returns:
        scoped_session 工厂。
    """
    global _SessionFactory
    _SessionFactory = scoped_session(
        sessionmaker(bind=engine, autoflush=False, autocommit=False)
    )
    return _SessionFactory


def get_session() -> Session:
    """返回当前线程的 Session。

    Raises:
        RuntimeError: 若未先调用 init_session_factory。
    """
    if _SessionFactory is None:
        raise RuntimeError('Session factory not initialized. Call init_session_factory first.')
    return _SessionFactory()


def remove_session() -> None:
    """移除当前线程的 Session（请求结束时调用）。"""
    if _SessionFactory is not None:
        _SessionFactory.remove()


def reset_session_factory() -> None:
    """重置 Session 工厂（测试清理用）。"""
    global _SessionFactory
    if _SessionFactory is not None:
        _SessionFactory.remove()
    _SessionFactory = None
