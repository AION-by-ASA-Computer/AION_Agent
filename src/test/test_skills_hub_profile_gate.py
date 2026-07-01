"""skills_hub skill_view must respect profile.skills allowlist."""

from __future__ import annotations

import os

import pytest

import importlib.util
from pathlib import Path

_repo = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "skills_hub_server_runtime",
    _repo / "mcp_servers" / "skills_hub" / "server.py",
)
skills_hub_server = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(skills_hub_server)


@pytest.fixture(autouse=True)
def _load_profiles(monkeypatch):
    monkeypatch.setenv("AION_SKILL_VIEW_ENFORCE_PROFILE", "1")
    from src.agent_profile import profile_manager

    profile_manager.load_all()


def test_skill_view_denies_skill_not_on_profile(monkeypatch):
    monkeypatch.setenv("AION_CURRENT_PROFILE_SLUG", "postgres_metadata_assistant")
    out = skills_hub_server.skill_view("db_navigation_map", materialize=False)
    assert "is not enabled in the active profile" in out
    assert "db_navigation_map" in out


def test_skill_view_allows_profile_skill(monkeypatch):
    monkeypatch.setenv("AION_CURRENT_PROFILE_SLUG", "postgres_metadata_assistant")
    out = skills_hub_server.skill_view("core_protocol", materialize=False)
    assert "is not enabled in the active profile" not in out
    assert len(out) > 40


def test_skill_view_denies_office_skill_not_on_profile(monkeypatch):
    monkeypatch.setenv("AION_CURRENT_PROFILE_SLUG", "postgres_metadata_assistant")
    out = skills_hub_server.skill_view("docx", materialize=False)
    assert "is not enabled in the active profile" in out
    assert "docx" in out


def test_skill_list_excludes_unallowed_office_skills(monkeypatch):
    monkeypatch.setenv("AION_CURRENT_PROFILE_SLUG", "postgres_metadata_assistant")
    from src.agent_profile import profile_manager
    print("\n--- DEBUG TEST ---")
    print("profile_manager.base_path:", profile_manager.base_path)
    print("profile_manager._by_slug keys:", list(profile_manager._by_slug.keys()))
    print("AION_CURRENT_PROFILE_SLUG:", os.environ.get("AION_CURRENT_PROFILE_SLUG"))
    print("AION_CHAT_SESSION_ID:", os.environ.get("AION_CHAT_SESSION_ID"))
    print("Allowed skill names:", skills_hub_server._profile_allowed_skill_names())
    out = skills_hub_server.skill_list()
    for slug in ("docx", "pdf", "xlsx", "pptx"):
        assert f"- {slug}:" not in out
