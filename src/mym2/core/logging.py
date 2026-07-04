"""MYM2 统一日志配置。

提供应用级日志设置和未捕获异常处理器。
"""

import logging
import re
import sys
import traceback
from pathlib import Path

_logger: logging.Logger | None = None

_SECRET_ASSIGNMENT_RE = re.compile(
    r'(?i)\b(api[_-]?key|password_hash|proxy_password|password|secret|token|key)'
    r'\s*([=:])\s*([^\s,;]+)'
)
_OPENAI_STYLE_KEY_RE = re.compile(r'\bsk-[A-Za-z0-9_-]{6,}\b')
_POSIX_PATH_RE = re.compile(r'(?<!\w)/(?:[^/\s:]+/)+[^/\s,)]+')
_WINDOWS_PATH_RE = re.compile(r'\b[A-Za-z]:\\(?:[^\\\s:]+\\)+[^\\\s,)]+')


def redact_text(text: str) -> str:
    """脱敏日志文本中的路径、密钥与密码类字段。"""
    text = _SECRET_ASSIGNMENT_RE.sub(r'\1\2<redacted>', text)
    text = _OPENAI_STYLE_KEY_RE.sub('sk-<redacted>', text)
    text = _POSIX_PATH_RE.sub('<path>', text)
    text = _WINDOWS_PATH_RE.sub('<path>', text)
    return text


class RedactingFormatter(logging.Formatter):
    """最终输出前脱敏日志文本。"""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


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

    fmt = RedactingFormatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    root = logging.getLogger('mym2')
    root.disabled = False
    root.propagate = False
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
