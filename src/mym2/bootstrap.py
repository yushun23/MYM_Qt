"""MYM2 应用启动引导。

负责：创建 QApplication、初始化日志、设置全局样式、创建主窗口。
"""

import logging
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from mym2.core.logging import install_excepthook, setup_logging
from mym2.core.paths import get_logs_dir, set_data_dir
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
) -> MainWindow:
    """初始化 MYM2 应用并返回主窗口。

    Args:
        data_dir: 覆写用户数据目录（测试/开发用）。
        log_level: 日志级别。

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

    window = MainWindow()
    return window
