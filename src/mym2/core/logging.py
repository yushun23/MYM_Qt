"""MYM2 统一日志配置。

提供应用级日志设置和未捕获异常处理器。
"""

import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime
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


class StructuredJsonFormatter(logging.Formatter):
    """JSON Lines 结构化日志格式器，输出前执行脱敏。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': datetime.fromtimestamp(record.created, UTC).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return redact_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )


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

    # 结构化 JSONL 日志，供诊断包和后续排障使用。
    json_handler = logging.FileHandler(logs_dir / 'mym2.jsonl', encoding='utf-8')
    json_handler.setLevel(level)
    json_handler.setFormatter(StructuredJsonFormatter())
    root.addHandler(json_handler)

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
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None,
                    'MYM2 发生异常',
                    (
                        '程序遇到未处理异常，详细信息已写入日志。\n\n'
                        f'{redact_text(str(exc_value))}'
                    ),
                )
        except Exception:
            logger.exception('显示全局异常对话框失败')
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
