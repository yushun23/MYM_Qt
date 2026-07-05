"""PluginManifest – defines what a plugin declares about itself."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PluginManifest:
    """A plugin's declaration of identity, entry point, and permissions."""

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry_point: str = ""
    required_permissions: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    min_app_version: str = "0.1.0"
    max_app_version: str | None = None
    plugin_dir: Path | None = None

    @classmethod
    def from_file(cls, path: Path) -> PluginManifest | None:
        """Load manifest from a plugin.json file."""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            return None

        manifest = cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "")),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", ""),
            required_permissions=data.get("required_permissions", []),
            provides=data.get("provides", []),
            min_app_version=data.get("min_app_version", "0.1.0"),
            max_app_version=data.get("max_app_version"),
            plugin_dir=path.parent,
        )
        return manifest

    @classmethod
    def from_dict(cls, data: dict[str, Any], plugin_dir: Path | None = None) -> PluginManifest:
        """Create manifest from a dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "")),
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", ""),
            required_permissions=data.get("required_permissions", []),
            provides=data.get("provides", []),
            min_app_version=data.get("min_app_version", "0.1.0"),
            max_app_version=data.get("max_app_version"),
            plugin_dir=plugin_dir,
        )

    def is_valid(self) -> bool:
        """Check if manifest has required fields."""
        return bool(self.id and self.name and self.version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "entry_point": self.entry_point,
            "required_permissions": self.required_permissions,
            "provides": self.provides,
            "min_app_version": self.min_app_version,
            "max_app_version": self.max_app_version,
        }
