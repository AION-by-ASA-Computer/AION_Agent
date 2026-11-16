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


# --- Slug normalization and path traversal guard (CodeQL py/path-injection, alert #679) ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("aion_std", "aion_std"),  # valid slugs are left untouched (idempotent)
        ("Qualità & Rischi", "qualita_rischi"),
        ("Assistente HR (v2)", "assistente_hr_v2"),
        ("Sales.EU", "sales_eu"),
        ("sre-best-effort", "sre_best_effort"),  # '-' is not a valid stem char
        ("../../config/mcp_registry", "config_mcp_registry"),
        (r"..\..\evil", "evil"),  # Windows-style separators
        ("../", ""),
        ("???", ""),
    ],
)
def test_normalize_profile_slug(raw: str, expected: str) -> None:
    """Display names and hostile input map to a bare [a-z0-9_] stem (or '' to reject)."""
    assert ap.normalize_profile_slug(raw) == expected


@pytest.mark.parametrize("bad", ["../sre", "a/b", r"a\b", "", "Sre", "x.y"])
def test_profile_yaml_path_rejects_unsafe_slugs(
    pm: ap.ProfileManager, bad: str
) -> None:
    """profile_yaml_path refuses any slug that is not a canonical stem, read or write."""
    with pytest.raises(ap.InvalidProfileSlugError):
        pm.profile_yaml_path(bad)
    with pytest.raises(ap.InvalidProfileSlugError):
        pm.profile_yaml_path(bad, for_write=True)


def test_profile_yaml_path_stays_inside_profiles_dir(pm: ap.ProfileManager) -> None:
    """A valid slug resolves to a file directly inside the profiles directory."""
    path = pm.profile_yaml_path("sre", for_write=True)
    assert path.parent == pm.write_path.resolve()
    assert path.name == "sre.yaml"


def test_save_with_traversal_slug_writes_inside_profiles_dir(
    pm: ap.ProfileManager, tmp_path: Path
) -> None:
    """A '../' slug is normalized: the file lands in the profiles dir, never outside."""
    out = asyncio.run(
        admin.save_profile(
            ProfileUpdate(
                slug="../escaped",
                name="Escaped",
                description="d",
                instructions="i",
                skills=[],
                mcp_servers=[],
            )
        )
    )
    assert out["slug"] == "escaped"
    assert (pm.write_path / "escaped.yaml").is_file()
    assert not (tmp_path.parent / "escaped.yaml").exists()


def test_save_new_profile_from_display_name(pm: ap.ProfileManager) -> None:
    """A new profile named with accents/symbols gets a clean slug and is loadable."""
    out = asyncio.run(
        admin.save_profile(
            ProfileUpdate(
                name="Qualità & Rischi",
                description="d",
                instructions="i",
                skills=[],
                mcp_servers=[],
            )
        )
    )
    assert out["slug"] == "qualita_rischi"
    p = pm.get_profile("qualita_rischi")
    assert p is not None
    assert p.name == "Qualità & Rischi"  # display name is preserved


def test_save_rejects_name_without_usable_characters(pm: ap.ProfileManager) -> None:
    """A slug that normalizes to nothing is rejected with 400 and writes no file."""
    before = sorted(x.name for x in pm.write_path.iterdir())
    with pytest.raises(admin.HTTPException) as exc:
        asyncio.run(
            admin.save_profile(
                ProfileUpdate(
                    slug="../",
                    name="???",
                    description="d",
                    instructions="i",
                    skills=[],
                    mcp_servers=[],
                )
            )
        )
    assert exc.value.status_code == 400
    assert sorted(x.name for x in pm.write_path.iterdir()) == before
