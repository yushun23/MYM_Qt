"""MYM2 应用启动引导。

负责：创建 QApplication、初始化日志、数据库迁移、设置全局样式、创建主窗口。
"""

import logging
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from mym2.core.logging import install_excepthook, setup_logging
from mym2.core.paths import get_db_path, get_logs_dir, set_data_dir
from mym2.db.engine import create_mym2_engine
from mym2.db.ensure_schema import ensure_budget_columns
from mym2.db.migrate import upgrade_to_head
from mym2.db.session import init_session_factory
from mym2.ui.main_window import MainWindow

GLOBAL_STYLE = """
QMainWindow {
    background: #1e1f2b;
}
QWidget {
    font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
    color: #ddd;
}
"""


def bootstrap(
    *,
    data_dir: Path | None = None,
    log_level: int = logging.INFO,
    auto_migrate: bool = True,
) -> MainWindow:
    """初始化 MYM2 应用并返回主窗口。

    Args:
        data_dir: 覆写用户数据目录（测试/开发用）。
        log_level: 日志级别。
        auto_migrate: 是否自动运行数据库迁移（测试可设为 False）。

    Returns:
        已初始化但未显示的 MainWindow 实例。
    """
    if data_dir is not None:
        set_data_dir(data_dir)

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setApplicationName('MYM2')
    app.setApplicationVersion('0.1.0')
    app.setOrganizationName('MYM2')
    app.setStyleSheet(GLOBAL_STYLE)

    font = QFont()
    font.setPointSize(11)
    app.setFont(font)

    # 日志
    logger = setup_logging(get_logs_dir(), level=log_level)
    install_excepthook(logger)
    logger.info('MYM2 启动 — 版本 %s', '0.1.0')

    # 数据库迁移
    db_path = get_db_path()
    if auto_migrate:
        upgrade_to_head(db_path)
        logger.info('数据库路径: %s', db_path)

    engine = create_mym2_engine(db_path)
    init_session_factory(engine)

    # 确保 budget 扩展列存在（幂等添加）
    ensure_budget_columns(engine)

    window = MainWindow()
    return window

