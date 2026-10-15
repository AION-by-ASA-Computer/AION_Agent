"""POST /admin/skills/{name}/rename keeps profiles pointing at the renamed skill."""

import pytest
import yaml
from fastapi import HTTPException

from src.api import admin
from src.agent_profile import ProfileManager
from src.skill_registry import SkillRegistry


def _setup(monkeypatch, tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "old_name.md").write_text(
        "---\nname: old_name\ndescription: demo\ntags: [a]\n---\nBody\n",
        encoding="utf-8",
    )
    (skills / "other.md").write_text("---\nname: other\n---\nX\n", encoding="utf-8")
    reg = SkillRegistry(
        curated_dir=str(skills),
        curated_fallback_dir=str(tmp_path / "none"),
        generated_dir=str(tmp_path / "gen"),
    )
    reg.curated_dir, reg.curated_fallback_dir, reg.generated_dir = (
        skills,
        tmp_path / "none",
        tmp_path / "gen",
    )
    reg.load_all()
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "p1.yaml").write_text(
        yaml.dump(
            {
                "name": "p1",
                "skills": ["old_name", "other"],
                "critical_skills": ["old_name"],
                "mcp_servers": [],
            }
        ),
        encoding="utf-8",
    )
    (profiles / "p2.yaml").write_text(
        yaml.dump({"name": "p2", "skills": ["other"], "mcp_servers": []}),
        encoding="utf-8",
    )
    pm = ProfileManager(profiles_dir=str(profiles))
    monkeypatch.setattr(admin, "skill_registry", reg)
    monkeypatch.setattr(admin, "profile_manager", pm)
    return reg, profiles, skills


@pytest.mark.anyio
async def test_rename_updates_file_and_profiles(monkeypatch, tmp_path):
    reg, profiles, skills = _setup(monkeypatch, tmp_path)
    res = await admin.rename_skill("old_name", admin.SkillRename(new_name="New Name"))
    assert res["name"] == "new_name" and res["profiles"] == ["p1"]
    assert not (skills / "old_name.md").exists() and (skills / "new_name.md").exists()
    assert reg.skill_exists("new_name") and not reg.skill_exists("old_name")
    p1 = yaml.safe_load((profiles / "p1.yaml").read_text())
    assert p1["skills"] == ["new_name", "other"] and p1["critical_skills"] == [
        "new_name"
    ]


@pytest.mark.anyio
async def test_rename_rejects_conflict_and_bad_name(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as e:
        await admin.rename_skill("old_name", admin.SkillRename(new_name="other"))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        await admin.rename_skill("old_name", admin.SkillRename(new_name="bad/name"))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await admin.rename_skill("missing", admin.SkillRename(new_name="x"))
    assert e.value.status_code == 404


@pytest.mark.anyio
async def test_rename_does_not_resurrect_shipped_copy(monkeypatch, tmp_path):
    reg, profiles, skills = _setup(monkeypatch, tmp_path)
    std = tmp_path / "std"
    std.mkdir()
    (std / "old_name.md").write_text(
        "---\nname: old_name\n---\nShipped\n", encoding="utf-8"
    )
    reg.curated_fallback_dir = std
    reg.load_all()
    await admin.rename_skill("old_name", admin.SkillRename(new_name="new_name"))
    assert reg.skill_exists("new_name")
    assert not reg.skill_exists("old_name")
    reg.load_all()
    assert not reg.skill_exists("old_name")
    # Renaming back must work and clear the hidden marker.
    await admin.rename_skill("new_name", admin.SkillRename(new_name="old_name"))
    assert reg.skill_exists("old_name") and not reg.skill_exists("new_name")
