"""Tests for src/utils/i18n.py"""

import json

import pytest

from src.utils import i18n


@pytest.fixture(autouse=True)
def _reset_translations():
    """Reset global translation state before/after each test."""
    i18n._translations = {}
    i18n._current_lang = "en"
    yield
    i18n._translations = {}
    i18n._current_lang = "en"


class TestLoadTranslations:
    def test_loads_valid_file(self, tmp_path):
        p = tmp_path / "translations.json"
        p.write_text(json.dumps({"en": {"hello": "Hello"}, "ar": {"hello": "مرحبا"}}), encoding="utf-8")
        assert i18n.load_translations(str(p), lang="en") is True
        assert i18n.tr("hello") == "Hello"

    def test_missing_file_returns_false(self, tmp_path):
        assert i18n.load_translations(str(tmp_path / "nope.json")) is False

    def test_invalid_json_returns_false(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert i18n.load_translations(str(p)) is False

    def test_missing_language_falls_back(self, tmp_path):
        p = tmp_path / "translations.json"
        p.write_text(json.dumps({"en": {"hello": "Hello"}}), encoding="utf-8")
        # lang 'fr' not present — should still return True but warn
        assert i18n.load_translations(str(p), lang="fr") is True


class TestTr:
    def test_existing_key(self, tmp_path):
        p = tmp_path / "translations.json"
        p.write_text(json.dumps({"en": {"welcome": "Welcome"}}), encoding="utf-8")
        i18n.load_translations(str(p), lang="en")
        assert i18n.tr("welcome") == "Welcome"

    def test_missing_key_returns_default(self, tmp_path):
        p = tmp_path / "translations.json"
        p.write_text(json.dumps({"en": {}}), encoding="utf-8")
        i18n.load_translations(str(p), lang="en")
        assert i18n.tr("missing_key") == "missing_key"
        assert i18n.tr("missing_key", default="Fallback") == "Fallback"

    def test_language_switch(self, tmp_path):
        p = tmp_path / "translations.json"
        p.write_text(json.dumps({
            "en": {"greet": "Hello"},
            "fr": {"greet": "Bonjour"},
        }), encoding="utf-8")
        i18n.load_translations(str(p), lang="en")
        assert i18n.tr("greet") == "Hello"
        i18n.set_language("fr")
        assert i18n.tr("greet") == "Bonjour"


class TestSetLanguage:
    def test_set_language_changes_current(self):
        i18n.set_language("de")
        assert i18n._current_lang == "de"
