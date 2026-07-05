"""Resources module – paths to bundled assets."""

from pathlib import Path

_RESOURCES_DIR = Path(__file__).resolve().parent


def get_echarts_js() -> Path:
    """Return absolute path to local echarts.min.js."""
    return _RESOURCES_DIR / "echarts" / "echarts.min.js"


def get_assets_dir() -> Path:
    """Return absolute path to assets directory."""
    return _RESOURCES_DIR / "assets"
