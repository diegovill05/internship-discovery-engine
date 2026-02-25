"""Unit tests for internship_engine.config.

Verifies that Settings can be constructed without error and that
all fields carry their expected defaults when no environment
variables are set.
"""

from __future__ import annotations

import pytest

from internship_engine.config import Settings, get_settings, reset_settings


@pytest.fixture(autouse=True)
def _reset():
    """Reset the singleton before and after every test."""
    reset_settings()
    yield
    reset_settings()


class TestSettingsConstruction:
    def test_constructs_without_error(self):
        s = Settings()
        assert s is not None

    def test_get_settings_returns_settings_instance(self):
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_is_singleton(self):
        assert get_settings() is get_settings()

    def test_reset_settings_clears_singleton(self):
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2


class TestSettingsDefaults:
    def test_allowed_locations_default_is_empty_list(self):
        assert Settings().allowed_locations == []

    def test_target_categories_default(self):
        assert Settings().target_categories == ["software", "data", "product"]

    def test_remote_included_default_is_true(self):
        assert Settings().remote_included is True

    def test_brave_api_key_default_is_empty_string(self):
        assert Settings().brave_api_key == ""

    def test_google_api_key_default_is_empty_string(self):
        assert Settings().google_api_key == ""

    def test_google_cse_id_default_is_empty_string(self):
        assert Settings().google_cse_id == ""

    def test_seen_hashes_path_default(self):
        from pathlib import Path

        assert Settings().seen_hashes_path == Path(".cache/seen_hashes.txt")


class TestSettingsEnvOverride:
    def test_brave_api_key_read_from_env(self, monkeypatch):
        monkeypatch.setenv("IE_BRAVE_API_KEY", "test-brave-key")
        assert Settings().brave_api_key == "test-brave-key"

    def test_google_api_key_read_from_env(self, monkeypatch):
        monkeypatch.setenv("IE_GOOGLE_API_KEY", "test-google-key")
        assert Settings().google_api_key == "test-google-key"

    def test_remote_included_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("IE_REMOTE_INCLUDED", "false")
        assert Settings().remote_included is False

    def test_allowed_locations_parsed_from_json_array(self, monkeypatch):
        monkeypatch.setenv("IE_ALLOWED_LOCATIONS", '["New York","Austin"]')
        assert Settings().allowed_locations == ["New York", "Austin"]
