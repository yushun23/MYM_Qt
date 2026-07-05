"""Resource integrity check – verifies required assets are present at startup."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_REQUIRED_RESOURCES: list[tuple[str, str]] = [
    ("i18n/zh_CN.json", "Chinese translation file"),
    ("i18n/en.json", "English translation file"),
]


def check_resources(i18n_dir: Path) -> list[str]:
    """Check that required resource files exist.

    Args:
        i18n_dir: Path to the i18n directory.

    Returns:
        List of missing resource descriptions.
    """
    missing: list[str] = []

    for rel_path, description in _REQUIRED_RESOURCES:
        full_path = i18n_dir.parent / rel_path if "i18n" in rel_path else i18n_dir / rel_path
        if not full_path.exists():
            missing.append(f"{description} ({rel_path}) at {full_path}")

    if missing:
        logger.error("Missing required resources:")
        for m in missing:
            logger.error("  - %s", m)
    else:
        logger.info("All required resources present.")

    return missing
