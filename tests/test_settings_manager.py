"""Tests for src/utils/settings_manager.py"""

import json

import pytest

from src.utils.settings_manager import SettingsManager


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    """Point SETTINGS_FILE at a temp file and reset the class cache."""
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("src.utils.settings_manager.SETTINGS_FILE", settings_file)
    SettingsManager._cache = None
    yield settings_file
    SettingsManager._cache = None


class TestLoad:
    def test_load_returns_defaults_when_missing(self, _isolate_settings):
        settings = SettingsManager.load()
        assert settings["language"] == "en"
        assert settings["theme"] == "light"
        assert settings["clinic_name"] == "My PET Clinic"
        assert settings["window_mode"] == "windowed"
        assert settings["dev_mode"] is False

    def test_load_merges_with_file(self, _isolate_settings):
        settings_file = _isolate_settings
        settings_file.write_text(json.dumps({"theme": "dark", "custom_key": 42}), encoding="utf-8")

        settings = SettingsManager.load()
        assert settings["theme"] == "dark"
        assert settings["language"] == "en"  # default preserved
        assert settings["custom_key"] == 42  # extra key preserved

    def test_load_corrupt_file_returns_defaults(self, _isolate_settings):
        _isolate_settings.write_text("{not valid json", encoding="utf-8")
        settings = SettingsManager.load()
        assert settings["language"] == "en"

    def test_load_caches_result(self, _isolate_settings):
        first = SettingsManager.load()
        # Mutate the file; cached copy must be returned (no re-read).
        _isolate_settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        second = SettingsManager.load()
        assert second == first


class TestSave:
    def test_save_writes_file(self, _isolate_settings):
        data = {"language": "ar", "theme": "dark"}
        assert SettingsManager.save(data) is True
        on_disk = json.loads(_isolate_settings.read_text(encoding="utf-8"))
        assert on_disk == data

    def test_save_updates_cache(self, _isolate_settings):
        assert SettingsManager.save({"language": "fr"}) is True
        assert SettingsManager.load()["language"] == "fr"

    def test_save_leaves_no_temp_file_behind(self, _isolate_settings):
        assert SettingsManager.save({"language": "fr"}) is True
        assert list(_isolate_settings.parent.glob("settings.json.*")) == []

    def test_save_is_atomic_on_failure(self, _isolate_settings, monkeypatch):
        """A failed write must leave the previous file untouched."""
        settings_file = _isolate_settings
        settings_file.write_text(json.dumps({"language": "en"}), encoding="utf-8")

        def _boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr("src.utils.settings_manager.os.replace", _boom)

        assert SettingsManager.save({"language": "ar"}) is False
        assert json.loads(settings_file.read_text(encoding="utf-8")) == {"language": "en"}
        # The half-written temp file is cleaned up.
        assert list(settings_file.parent.glob("settings.json.*")) == []


class TestGetSet:
    def test_get_existing_and_default(self, _isolate_settings):
        assert SettingsManager.get("language") == "en"
        assert SettingsManager.get("does_not_exist") is None
        assert SettingsManager.get("does_not_exist", "fallback") == "fallback"

    def test_set_persists(self, _isolate_settings):
        assert SettingsManager.set("theme", "dark") is True
        assert SettingsManager.get("theme") == "dark"
        on_disk = json.loads(_isolate_settings.read_text(encoding="utf-8"))
        assert on_disk["theme"] == "dark"

    def test_set_preserves_other_keys(self, _isolate_settings):
        SettingsManager.set("theme", "dark")
        SettingsManager.set("dev_mode", True)
        settings = SettingsManager.load()
        assert settings["theme"] == "dark"
        assert settings["dev_mode"] is True
        assert settings["language"] == "en"
