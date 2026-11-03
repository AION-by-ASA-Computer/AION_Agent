"""POST /admin/profiles conserva le chiavi del YAML non gestite dall'admin-ui."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

import src.agent_profile as ap
import src.api.admin as admin
from src.api.admin import ProfileUpdate


@pytest.fixture
def pm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ap.ProfileManager:
    (tmp_path / "sre.yaml").write_text(
        yaml.dump(
            {
                "name": "SRE",
                "description": "old",
                "instructions": "old",
                "skills": [],
                "mcp_servers": [],
                "max_agent_steps": 12,
                "agent": {"max_steps": 12},
                "custom_key": "keep-me",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ap, "migrate_profiles_to_write_dir", lambda: None)
    mgr = ap.ProfileManager(str(tmp_path))
    monkeypatch.setattr(admin, "profile_manager", mgr)
    import src.runtime.profile_sync_state as pss

    monkeypatch.setattr(pss, "record_profile_after_admin_save", lambda _p: None)
    return mgr


def _update(**extra) -> ProfileUpdate:
    return ProfileUpdate(
        slug="sre",
        name="SRE",
        description="new",
        instructions="new",
        skills=[],
        mcp_servers=[],
        **extra,
    )


def _saved(pm: ap.ProfileManager) -> dict:
    return yaml.safe_load((pm.write_path / "sre.yaml").read_text(encoding="utf-8"))


def test_save_keeps_unmanaged_keys(pm: ap.ProfileManager) -> None:
    asyncio.run(admin.save_profile(_update()))
    data = _saved(pm)
    assert data["description"] == "new"
    assert data["max_agent_steps"] == 12
    assert data["agent"] == {"max_steps": 12}
    assert data["custom_key"] == "keep-me"
    assert pm.get_profile("sre").max_agent_steps == 12


def test_save_updates_and_clears_agent_fields(pm: ap.ProfileManager) -> None:
    asyncio.run(admin.save_profile(_update(max_agent_steps=30, agent=None)))
    data = _saved(pm)
    assert data["max_agent_steps"] == 30
    assert "agent" not in data


def test_get_and_export_include_agent_fields(pm: ap.ProfileManager) -> None:
    out = asyncio.run(admin.get_profile("sre"))
    assert out["slug"] == "sre"
    assert out["max_agent_steps"] == 12
    assert out["agent"] == {"max_steps": 12}

    (pm.write_path / "sre.yaml").unlink()
    exported = yaml.safe_load(asyncio.run(admin.export_profile_yaml("sre")).body)
    assert exported["max_agent_steps"] == 12
    assert "agent" not in exported
