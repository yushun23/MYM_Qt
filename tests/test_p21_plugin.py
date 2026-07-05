"""Tests for P21 – Plugin framework: manifest, manager, isolation."""

import tempfile
from pathlib import Path

import pytest

from mym.infrastructure.plugins.manifest import PluginManifest
from mym.infrastructure.plugins.manager import PluginManager, LoadedPlugin


@pytest.fixture
def plugins_dir():
    d = Path(tempfile.mkdtemp())
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestPluginManifest:
    def test_valid_manifest(self):
        m = PluginManifest(
            id="test_plugin",
            name="Test Plugin",
            version="1.0.0",
            entry_point="main.py",
        )
        assert m.is_valid()
        assert m.to_dict()["id"] == "test_plugin"

    def test_invalid_manifest(self):
        m = PluginManifest(id="", name="", version="")
        assert not m.is_valid()

    def test_from_dict(self):
        data = {
            "id": "my_plugin",
            "name": "My Plugin",
            "version": "2.0.0",
            "required_permissions": ["query_accounts"],
            "provides": ["import"],
        }
        m = PluginManifest.from_dict(data)
        assert m.id == "my_plugin"
        assert m.required_permissions == ["query_accounts"]
        assert m.provides == ["import"]

    def test_from_file(self, plugins_dir):
        plugin_dir = plugins_dir / "test_plugin"
        plugin_dir.mkdir()
        manifest_path = plugin_dir / "plugin.json"
        manifest_path.write_text('{"id": "test", "name": "Test", "version": "1.0.0"}')

        m = PluginManifest.from_file(manifest_path)
        assert m is not None
        assert m.id == "test"
        assert m.plugin_dir == plugin_dir

    def test_from_file_missing(self):
        m = PluginManifest.from_file(Path("/nonexistent/plugin.json"))
        assert m is None


class TestPluginManager:
    def test_discover_plugins(self, plugins_dir):
        # Create a plugin
        pdir = plugins_dir / "my_plugin"
        pdir.mkdir()
        (pdir / "plugin.json").write_text(
            '{"id": "my_plugin", "name": "My Plugin", "version": "1.0.0"}'
        )

        mgr = PluginManager(plugins_dir)
        manifests = mgr.discover()
        assert len(manifests) == 1
        assert manifests[0].id == "my_plugin"

    def test_discover_no_plugins(self, plugins_dir):
        mgr = PluginManager(plugins_dir)
        manifests = mgr.discover()
        assert manifests == []

    def test_discover_invalid_manifest(self, plugins_dir):
        pdir = plugins_dir / "bad_plugin"
        pdir.mkdir()
        (pdir / "plugin.json").write_text('{"id": ""}')  # invalid

        mgr = PluginManager(plugins_dir)
        manifests = mgr.discover()
        assert len(manifests) == 0

    def test_load_and_enable_plugin(self, plugins_dir):
        pdir = plugins_dir / "good_plugin"
        pdir.mkdir()
        (pdir / "plugin.json").write_text(
            '{"id": "good_plugin", "name": "Good", "version": "1.0.0", '
            '"entry_point": "main.py"}'
        )
        (pdir / "main.py").write_text('def run(): return "ok"')

        mgr = PluginManager(plugins_dir)
        manifests = mgr.discover()
        assert len(manifests) == 1

        loaded = mgr.load_plugin(manifests[0])
        assert loaded is not None
        assert loaded.status == "loaded"

        assert mgr.enable_plugin("good_plugin")
        assert loaded.status == "enabled"

    def test_cannot_load_nonexistent_entry(self, plugins_dir):
        pdir = plugins_dir / "no_entry"
        pdir.mkdir()
        (pdir / "plugin.json").write_text(
            '{"id": "no_entry", "name": "NoEntry", "version": "1.0.0", '
            '"entry_point": "missing.py"}'
        )

        mgr = PluginManager(plugins_dir)
        manifests = mgr.discover()
        loaded = mgr.load_plugin(manifests[0])
        assert loaded is not None
        # Should still be loaded (no error), just no module
        assert loaded.module is None

    def test_disable_plugin(self, plugins_dir):
        mgr = PluginManager(plugins_dir)
        manifest = PluginManifest(
            id="test", name="Test", version="1.0.0",
            plugin_dir=plugins_dir,
        )
        loaded = mgr.load_plugin(manifest)

        assert mgr.enable_plugin("test")
        assert mgr.disable_plugin("test")
        assert loaded.status == "disabled"

    def test_forbidden_permission(self, plugins_dir):
        mgr = PluginManager(plugins_dir)
        manifest = PluginManifest(
            id="bad_perm", name="BadPerm", version="1.0.0",
            required_permissions=["direct_db_access"],
            plugin_dir=plugins_dir,
        )
        mgr.load_plugin(manifest)
        assert not mgr.enable_plugin("bad_perm")
        loaded = mgr.plugins["bad_perm"]
        assert loaded.status == "error"
        assert "Forbidden permission" in loaded.error_message

    def test_unload_plugin(self, plugins_dir):
        mgr = PluginManager(plugins_dir)
        manifest = PluginManifest(
            id="tmp", name="Tmp", version="1.0.0",
            plugin_dir=plugins_dir,
        )
        mgr.load_plugin(manifest)
        mgr.enable_plugin("tmp")
        mgr.unload_plugin("tmp")
        assert "tmp" not in mgr.plugins

    def test_get_plugin_statuses(self, plugins_dir):
        mgr = PluginManager(plugins_dir)
        manifest = PluginManifest(
            id="s1", name="S1", version="1.0.0",
            description="First plugin",
            plugin_dir=plugins_dir,
        )
        mgr.load_plugin(manifest)
        mgr.enable_plugin("s1")

        statuses = mgr.get_plugin_statuses()
        assert len(statuses) == 1
        assert statuses[0]["id"] == "s1"
        assert statuses[0]["status"] == "enabled"

    def test_version_mismatch(self, plugins_dir):
        mgr = PluginManager(plugins_dir)
        mgr.set_app_version("0.0.1")  # Too old

        manifest = PluginManifest(
            id="new_plugin", name="New", version="1.0.0",
            min_app_version="0.1.0",
            plugin_dir=plugins_dir,
        )
        loaded = mgr.load_plugin(manifest)
        assert loaded is not None
        assert loaded.status == "error"
        assert "version" in loaded.error_message.lower()
