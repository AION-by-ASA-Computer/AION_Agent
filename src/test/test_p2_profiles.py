"""P2 Sprint 1 — profiles, aliases, mtime reload."""
import textwrap
import time
from pathlib import Path

import pytest

from src.agent_profile import ProfileManager, ProfileNotFoundError
from src.runtime.skill_alias import resolve_skill_alias


def test_resolve_skill_alias_matrix():
    assert resolve_skill_alias("core_protocol") == "core_protocol"
    assert resolve_skill_alias("artifact_protocol", "markdown") == "artifact_protocol_markdown"
    assert resolve_skill_alias("artifact_protocol", "tool") == "artifact_protocol_tool"
    assert resolve_skill_alias("artifact_protocol", "xml") == "artifact_protocol_xml"


def test_get_profile_slug_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AION_PROFILE_LEGACY_NAME_LOOKUP", "0")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "aion_std.yaml").write_text(
        textwrap.dedent(
            """
            name: AION Standard
            description: ok
            instructions: test
            skills: []
            mcp_servers: []
            """
        ),
        encoding="utf-8",
    )
    mgr = ProfileManager(profiles_dir=str(profiles))
    assert mgr.get_profile("aion_std") is not None
    assert mgr.get_profile("AION Standard") is None


def test_resolve_profile_unknown_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AION_DEFAULT_PROFILE", "__missing_default__")
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "aion_std.yaml").write_text(
        "name: AION\ninstructions: x\nskills: []\nmcp_servers: []\n",
        encoding="utf-8",
    )
    mgr = ProfileManager(profiles_dir=str(profiles))
    with pytest.raises(ProfileNotFoundError) as exc:
        mgr.resolve_profile("missing_slug")
    assert "missing_slug" in str(exc.value)
    assert "aion_std" in exc.value.available_slugs


def test_profile_mtime_no_reload(tmp_path: Path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    path = profiles / "orch.yaml"
    path.write_text(
        "name: Orch\ndescription: v1\ninstructions: x\nskills: []\nmcp_servers: []\n",
        encoding="utf-8",
    )
    mgr = ProfileManager(profiles_dir=str(profiles))
    first_mtime = mgr._dir_mtime
    mgr.load_all_if_stale()
    assert mgr._dir_mtime == first_mtime
    assert mgr.get_profile("orch").description == "v1"
    time.sleep(0.02)
    path.write_text(
        "name: Orch\ndescription: v2\ninstructions: x\nskills: []\nmcp_servers: []\n",
        encoding="utf-8",
    )
    mgr.load_all_if_stale()
    assert mgr.get_profile("orch").description == "v2"
