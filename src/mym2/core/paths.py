"""MYM2 用户数据路径管理。

使用 QStandardPaths 定位数据目录，防止在项目根目录写入用户数据。
仅在测试/开发模式允许显式覆写。
"""

from pathlib import Path

from PySide6.QtCore import QStandardPaths

_DATA_DIR_OVERRIDE: Path | None = None


def set_data_dir(path: Path) -> None:
    """覆写用户数据目录（仅限测试/开发使用）。

    正式运行中不应调用此函数。
    """
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = Path(path)


def get_data_dir() -> Path:
    """返回用户数据目录。

    优先级：显式覆写 > QStandardPaths AppLocalDataLocation。
    """
    if _DATA_DIR_OVERRIDE is not None:
        return _DATA_DIR_OVERRIDE
    base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    if not base:
        base = str(Path.home() / '.mym2')
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    """返回主数据库文件路径。"""
    return get_data_dir() / 'mym2.db'


def get_logs_dir() -> Path:
    """返回日志目录路径。"""
    logs = get_data_dir() / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    return logs


def get_backups_dir() -> Path:
    """返回备份目录路径。"""
    backups = get_data_dir() / 'backups'
    backups.mkdir(parents=True, exist_ok=True)
    return backups


def reset_override() -> None:
    """重置路径覆写（测试清理用）。"""
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = None
