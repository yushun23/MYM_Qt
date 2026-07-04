"""pytest 全局配置 — 确保 Qt 测试在无显示器环境可运行。"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from mym2.db.engine import create_mym2_engine
from mym2.db.migrate import upgrade_to_head
from mym2.db.session import init_session_factory, remove_session, reset_session_factory


def pytest_configure(config) -> None:
    """配置 Qt 使用 offscreen 平台。"""
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture
def session() -> Session:
    """创建独立的测试数据库会话。

    每个测试使用独立的临时 SQLite 数据库 + Alembic 迁移。
    测试结束后清理。
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="mym2_test_"))
    db_path = tmpdir / "test.db"

    try:
        reset_session_factory()
        engine = create_mym2_engine(str(db_path))
        upgrade_to_head(db_path)

        factory = init_session_factory(engine)
        s = factory()
        try:
            yield s
        finally:
            s.close()
            remove_session()
            reset_session_factory()
    finally:
        # 清理临时目录
        engine.dispose()
        shutil.rmtree(str(tmpdir), ignore_errors=True)
