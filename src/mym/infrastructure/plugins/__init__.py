"""Plugin framework – discovery, loading, isolation, and lifecycle management."""

from mym.infrastructure.plugins.manifest import PluginManifest
from mym.infrastructure.plugins.manager import PluginManager

__all__ = ["PluginManifest", "PluginManager"]
