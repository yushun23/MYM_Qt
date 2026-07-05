"""Application path service – platform-aware directory resolution for dev and packaged modes."""

import os
import sys
from pathlib import Path


def _is_frozen() -> bool:
    """True when running from a PyInstaller/pyside6-deploy bundle."""
    return getattr(sys, "frozen", False)


def get_app_root() -> Path:
    """Root of the application (project root in dev, extracted bundle dir in frozen)."""
    if _is_frozen():
        return Path(sys.executable).parent
    # Dev mode: this file is at src/mym/infrastructure/paths/app_paths.py
    # Go up 5 levels to reach project root
    return Path(__file__).resolve().parents[4]


def get_user_data_dir() -> Path:
    """Platform-specific user data directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.name == "posix" and hasattr(os, "uname") and "darwin" in os.uname().sysname.lower():
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "mym"


def get_ledger_dir() -> Path:
    """Default directory for ledger (.mym) files."""
    p = get_user_data_dir() / "ledgers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_backup_dir() -> Path:
    """Directory for ledger backups."""
    p = get_user_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_export_dir() -> Path:
    """Default directory for exports (CSV, XLSX, PDF, PNG)."""
    p = get_user_data_dir() / "exports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_temp_dir() -> Path:
    """Temporary files directory."""
    p = get_user_data_dir() / "temp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_log_dir() -> Path:
    """Log files directory."""
    p = get_user_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_assets_dir() -> Path:
    """Assets directory (i18n, echarts, icons, etc.)."""
    return get_app_root() / "src" / "mym" / "resources" / "assets"


def get_i18n_dir() -> Path:
    """Translation files directory."""
    return get_app_root() / "src" / "mym" / "resources" / "i18n"


def ensure_app_dirs() -> list[Path]:
    """Create all required application directories and return them."""
    dirs = [
        get_user_data_dir(),
        get_ledger_dir(),
        get_backup_dir(),
        get_export_dir(),
        get_temp_dir(),
        get_log_dir(),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return dirs
