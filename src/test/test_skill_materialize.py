"""Skill package scripts materialized into session workspace."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.session_workspace import session_root
from src.skill_registry import SkillRegistry
from src.tools.skill_materialize import materialize_skill_scripts


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_office_scripts_present_in_config_std():
    root = _repo_root() / "config_std" / "skills"
    for slug in ("docx", "pptx"):
        assert (root / slug / "scripts" / "office" / "unpack.py").is_file(), slug
    assert (root / "pdf" / "scripts").is_dir()
    assert (root / "xlsx" / "scripts" / "recalc.py").is_file()


def test_materialize_docx_into_session(isolated_data):
    sid = "test-materialize-docx"
    reg = SkillRegistry()
    reg.reload()
    assert reg.get_skill_scripts_dir("docx") is not None

    r1 = materialize_skill_scripts(sid, "docx")
    assert r1.status == "copied"
    assert (session_root(sid) / "scripts" / "office" / "unpack.py").is_file()
    assert "scripts/office/unpack.py" in r1.sentinel_paths

    r2 = materialize_skill_scripts(sid, "docx")
    assert r2.status == "skipped"

    marker = session_root(sid) / ".aion_skill_assets" / "docx.json"
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data.get("slug") == "docx"
    assert data.get("fingerprint")


def test_materialize_force_recopies(isolated_data):
    sid = "test-materialize-force"
    materialize_skill_scripts(sid, "docx")
    unpack = session_root(sid) / "scripts" / "office" / "unpack.py"
    assert unpack.is_file()
    old = unpack.read_text(encoding="utf-8")
    unpack.write_text(old + "\n# touched\n", encoding="utf-8")
    r = materialize_skill_scripts(sid, "docx", force=True)
    assert r.status == "copied"
    assert "# touched" not in unpack.read_text(encoding="utf-8")


def test_registry_package_root():
    reg = SkillRegistry()
    reg.reload()
    root = reg.get_skill_package_root("docx")
    assert root is not None
    assert (root / "SKILL.md").is_file()
    assert reg.get_skill_scripts_dir("docx") == root / "scripts"


def test_materialize_unknown_skill(isolated_data):
    r = materialize_skill_scripts("sess-x", "no_such_skill_xyz")
    assert r.status == "not_found"
