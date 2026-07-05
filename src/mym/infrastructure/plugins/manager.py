"""PluginManager – discovers, loads, isolates, and manages plugin lifecycle."""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .manifest import PluginManifest

logger = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    """A plugin that has been loaded into memory."""

    manifest: PluginManifest
    module: Any | None = None
    instance: Any | None = None
    status: str = "loaded"  # loaded, enabled, disabled, error
    error_message: str | None = None

    def is_enabled(self) -> bool:
        return self.status == "enabled"


class PluginManager:
    """Manages plugin discovery, loading, enable/disable, and isolation."""

    # Permitted API – plugins can only use these services
    ALLOWED_APIS = frozenset({
        "query_transactions",
        "query_accounts",
        "query_categories",
        "import_transactions",
        "export_data",
    })

    def __init__(self, plugins_dir: Path | None = None) -> None:
        self._plugins_dir = plugins_dir
        self._plugins: dict[str, LoadedPlugin] = {}
        self._enabled_ids: set[str] = set()
        self._app_version = "0.1.0"

    @property
    def plugins(self) -> dict[str, LoadedPlugin]:
        return self._plugins

    def set_plugins_dir(self, path: Path) -> None:
        self._plugins_dir = path

    def set_enabled_plugins(self, plugin_ids: list[str]) -> None:
        """Set which plugins should be enabled (from settings)."""
        self._enabled_ids = set(plugin_ids)

    def set_app_version(self, version: str) -> None:
        self._app_version = version

    def discover(self) -> list[PluginManifest]:
        """Scan plugins directory for plugin.json files."""
        if not self._plugins_dir or not self._plugins_dir.exists():
            logger.info("Plugins directory not found: %s", self._plugins_dir)
            return []

        manifests: list[PluginManifest] = []
        for item in self._plugins_dir.iterdir():
            if not item.is_dir():
                continue
            manifest_path = item / "plugin.json"
            if not manifest_path.exists():
                continue
            manifest = PluginManifest.from_file(manifest_path)
            if manifest and manifest.is_valid():
                manifests.append(manifest)
                logger.debug("Discovered plugin: %s v%s", manifest.id, manifest.version)
            else:
                logger.warning("Invalid plugin manifest: %s", manifest_path)

        logger.info("Discovered %d plugin(s)", len(manifests))
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> LoadedPlugin | None:
        """Load a plugin's entry point module. Errors are isolated."""
        if manifest.id in self._plugins:
            return self._plugins[manifest.id]

        # Version check
        if not self._check_version(manifest):
            loaded = LoadedPlugin(
                manifest=manifest,
                status="error",
                error_message=f"App version {self._app_version} not compatible "
                              f"(requires {manifest.min_app_version}–{manifest.max_app_version})",
            )
            self._plugins[manifest.id] = loaded
            logger.warning("Plugin %s version mismatch", manifest.id)
            return loaded

        # Load module
        module = None
        try:
            if manifest.entry_point and manifest.plugin_dir:
                entry_path = manifest.plugin_dir / manifest.entry_point
                if entry_path.exists():
                    spec = importlib.util.spec_from_file_location(
                        f"plugin_{manifest.id}", str(entry_path)
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[f"plugin_{manifest.id}"] = module
                        spec.loader.exec_module(module)
        except Exception as e:
            logger.exception("Failed to load plugin %s: %s", manifest.id, e)
            loaded = LoadedPlugin(
                manifest=manifest,
                status="error",
                error_message=str(e),
            )
            self._plugins[manifest.id] = loaded
            return loaded

        loaded = LoadedPlugin(manifest=manifest, module=module, status="loaded")
        self._plugins[manifest.id] = loaded
        logger.info("Plugin loaded: %s v%s", manifest.id, manifest.version)
        return loaded

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a loaded plugin."""
        if plugin_id not in self._plugins:
            logger.warning("Plugin not loaded: %s", plugin_id)
            return False

        loaded = self._plugins[plugin_id]
        if loaded.status == "error":
            logger.warning("Cannot enable plugin with error: %s", plugin_id)
            return False

        # Verify permissions
        manifest = loaded.manifest
        for perm in manifest.required_permissions:
            if perm not in self.ALLOWED_APIS:
                logger.error(
                    "Plugin %s requires forbidden permission: %s", plugin_id, perm
                )
                loaded.status = "error"
                loaded.error_message = f"Forbidden permission: {perm}"
                return False

        loaded.status = "enabled"
        self._enabled_ids.add(plugin_id)
        logger.info("Plugin enabled: %s", plugin_id)
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a plugin without unloading."""
        if plugin_id not in self._plugins:
            return False
        self._plugins[plugin_id].status = "disabled"
        self._enabled_ids.discard(plugin_id)
        logger.info("Plugin disabled: %s", plugin_id)
        return True

    def unload_plugin(self, plugin_id: str) -> None:
        """Completely unload a plugin and remove from registry."""
        if plugin_id in self._plugins:
            del self._plugins[plugin_id]
            self._enabled_ids.discard(plugin_id)
            # Remove from sys.modules
            mod_name = f"plugin_{plugin_id}"
            if mod_name in sys.modules:
                del sys.modules[mod_name]
            logger.info("Plugin unloaded: %s", plugin_id)

    def get_enabled_plugins(self) -> list[LoadedPlugin]:
        return [p for p in self._plugins.values() if p.is_enabled()]

    def get_plugin_statuses(self) -> list[dict[str, Any]]:
        """Get status of all discovered/loaded plugins for UI display."""
        result = []
        for pid, loaded in self._plugins.items():
            result.append({
                "id": pid,
                "name": loaded.manifest.name,
                "version": loaded.manifest.version,
                "description": loaded.manifest.description,
                "status": loaded.status,
                "error": loaded.error_message,
                "provides": loaded.manifest.provides,
            })
        return result

    def _check_version(self, manifest: PluginManifest) -> bool:
        """Check if plugin version constraints are compatible."""
        # Simple semver-ish check
        try:
            app_parts = [int(x) for x in self._app_version.split(".")]
            min_parts = [int(x) for x in manifest.min_app_version.split(".")]
            if app_parts < min_parts:
                return False
            if manifest.max_app_version:
                max_parts = [int(x) for x in manifest.max_app_version.split(".")]
                if app_parts > max_parts:
                    return False
        except (ValueError, AttributeError):
            pass
        return True
