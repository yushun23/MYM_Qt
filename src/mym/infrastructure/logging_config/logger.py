"""Application logging setup with file rotation and crash handling."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_app_data_dir() -> Path:
    """Get the platform-appropriate application data directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.name == "posix" and "darwin" in os.uname().sysname.lower():
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "mym"


def setup_logging() -> Path:
    """Configure application logging.

    Returns:
        Path to the log directory.
    """
    app_data = get_app_data_dir()
    log_dir = app_data / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("mym")
    root_logger.setLevel(logging.DEBUG)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_dir / "mym.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Console handler for development
    if os.environ.get("MYM_DEBUG"):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(file_formatter)
        root_logger.addHandler(console_handler)

    root_logger.info("Logging initialized. Log directory: %s", log_dir)
    return log_dir
