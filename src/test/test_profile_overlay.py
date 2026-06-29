"""Profile std + writable overlay merge and migration."""
import os
import textwrap
from pathlib import Path

import pytest

from src.agent_profile import ProfileManager, migrate_profiles_to_write_dir


@pytest.fixture
def profile_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    std = tmp_path / "config" / "profiles"
    template = tmp_path / "config_std" / "profiles"
    overlay = tmp_path / "data" / "profiles"
    std.mkdir(parents=True)
    template.mkdir(parents=True)
    overlay.mkdir(parents=True)
    monkeypatch.setenv("AION_PROFILES_STD_DIR", str(std))
    monkeypatch.setenv("AION_PROFILES_WRITE_DIR", str(overlay))
    monkeypatch.setenv("AION_PROFILES_TEMPLATE_DIR", str(template))
    return std, template, overlay


def _write_profile(path: Path, slug: str, *, name: str, instructions: str = "base") -> None:
    path.write_text(
        textwrap.dedent(
            f"""
            name: {name}
            description: d
            instructions: {instructions}
            skills: []
            mcp_servers: []
            """
        ),
        encoding="utf-8",
    )


def test_overlay_wins_over_std(profile_dirs):
    std, template, overlay = profile_dirs
    _write_profile(std / "aion_std.yaml", "aion_std", name="Std")
    _write_profile(template / "aion_std.yaml", "aion_std", name="Template")
    _write_profile(overlay / "aion_std.yaml", "aion_std", name="Custom", instructions="edited")

    mgr = ProfileManager()
    p = mgr.get_profile("aion_std")
    assert p is not None
    assert p.name == "Custom"
    assert "edited" in p.instructions


def test_migrate_copies_customized_std_profile(profile_dirs):
    std, template, overlay = profile_dirs
    _write_profile(template / "aion_std.yaml", "aion_std", name="Template", instructions="from git")
    _write_profile(std / "aion_std.yaml", "aion_std", name="Local", instructions="admin edit")
    assert not (overlay / "aion_std.yaml").exists()

    copied = migrate_profiles_to_write_dir()
    assert copied == 1
    assert (overlay / "aion_std.yaml").is_file()
    assert "admin edit" in (overlay / "aion_std.yaml").read_text(encoding="utf-8")


def test_migrate_skips_identical_to_template(profile_dirs):
    std, template, overlay = profile_dirs
    body = textwrap.dedent(
        """
        name: Same
        description: d
        instructions: same
        skills: []
        mcp_servers: []
        """
    )
    (template / "foo.yaml").write_text(body, encoding="utf-8")
    (std / "foo.yaml").write_text(body, encoding="utf-8")

    copied = migrate_profiles_to_write_dir()
    assert copied == 0
    assert not (overlay / "foo.yaml").exists()


def test_admin_write_path(profile_dirs):
    std, template, overlay = profile_dirs
    _write_profile(std / "aion_std.yaml", "aion_std", name="Std")
    _write_profile(template / "aion_std.yaml", "aion_std", name="Template")

    mgr = ProfileManager()
    write = mgr.profile_yaml_path("aion_std", for_write=True)
    assert write.parent == overlay
    write.parent.mkdir(parents=True, exist_ok=True)
    _write_profile(write, "aion_std", name="Saved", instructions="via admin")

    mgr.load_all()
    p = mgr.get_profile("aion_std")
    assert p is not None
    assert p.name == "Saved"
