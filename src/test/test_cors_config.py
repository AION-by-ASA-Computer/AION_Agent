"""CORS settings: production must not use open wildcard by default."""
import os

import pytest

from src.api.cors_config import resolve_cors_settings


@pytest.fixture(autouse=True)
def _clean_cors_env(monkeypatch):
    for key in (
        "AION_CORS_ORIGINS",
        "AION_CORS_ALLOW_WILDCARD",
        "AION_ENV",
        "AION_PUBLIC_API_URL",
        "AION_ADMIN_UI_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_prod_wildcard_without_flag_uses_restricted_list(monkeypatch):
    monkeypatch.setenv("AION_ENV", "prod")
    monkeypatch.setenv("AION_CORS_ORIGINS", "*")
    settings = resolve_cors_settings()
    assert settings.allow_origin_regex is None
    assert "http://localhost:8003" in settings.allow_origins


def test_dev_wildcard_allowed(monkeypatch):
    monkeypatch.setenv("AION_ENV", "dev")
    monkeypatch.setenv("AION_CORS_ORIGINS", "*")
    settings = resolve_cors_settings()
    assert settings.allow_origin_regex == ".*"


def test_explicit_origin_list(monkeypatch):
    monkeypatch.setenv("AION_CORS_ORIGINS", "https://app.example.com,https://admin.example.com")
    settings = resolve_cors_settings()
    assert settings.allow_origin_regex is None
    assert settings.allow_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]
