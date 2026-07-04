"""MYM2 统一日志配置。

提供应用级日志设置和未捕获异常处理器。
"""

import logging
import sys
import traceback
from pathlib import Path

_logger: logging.Logger | None = None


def get_logger(name: str = 'mym2') -> logging.Logger:
    """返回 MYM2 日志记录器。

    若尚未初始化，返回一个最小可用的 logger。
    """
    global _logger
    if _logger is not None:
        return _logger.getChild(name) if name != 'mym2' else _logger
    return logging.getLogger(name)


def setup_logging(logs_dir: Path, *, level: int = logging.INFO) -> logging.Logger:
    """初始化应用级日志。

    Args:
        logs_dir: 日志文件输出目录。
        level: 日志级别，默认 INFO。

    Returns:
        mym2 根 logger。
    """
    global _logger

    logs_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    root = logging.getLogger('mym2')
    root.setLevel(level)
    root.handlers.clear()

    # 文件 handler
    file_handler = logging.FileHandler(logs_dir / 'mym2.log', encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 控制台 handler（仅 WARNING 及以上）
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING)
    console.setFormatter(fmt)
    root.addHandler(console)

    _logger = root
    return root


def install_excepthook(logger: logging.Logger) -> None:
    """安装未捕获异常全局处理器。

    将未捕获异常写入日志并显示错误对话框（若 QApplication 已存在）。
    """

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical('未捕获异常:\n%s', tb_text)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
