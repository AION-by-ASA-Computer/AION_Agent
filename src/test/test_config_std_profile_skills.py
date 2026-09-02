"""config_std profiles must reference skill slugs that SkillRegistry actually loads."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.skill_registry import SkillRegistry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _artifact_skill_loaded(reg: SkillRegistry) -> bool:
    return bool(reg.get_skill_full("artifact_protocol"))


def _profiles() -> list[tuple[Path, dict]]:
    profiles_dir = _repo_root() / "config_std" / "profiles"
    out = []
    for path in sorted(profiles_dir.glob("*.yaml")):
        out.append((path, yaml.safe_load(path.read_text(encoding="utf-8")) or {}))
    return out


def test_long_document_protocol_skill_exists():
    reg = SkillRegistry()
    reg.reload()
    assert reg.get_skill_full("long_document_protocol"), (
        "config_std/skills/long_document_protocol.md must be loadable"
    )


def test_profiles_with_ocr_declare_long_document_protocol():
    """A profile that can ingest documents must carry the protocol for long ones.

    Without it the model falls back to ocr_file on the whole PDF, which times out.
    """
    # Image-only workflows do not need the multi-page protocol.
    exempt = {"graphic_designer.yaml"}
    for path, data in _profiles():
        if path.name in exempt:
            continue
        if "ocr" not in (data.get("mcp_servers") or []):
            continue
        assert "long_document_protocol" in (data.get("skills") or []), (
            f"{path.name} mounts the ocr MCP server but does not list "
            "long_document_protocol"
        )


def test_config_std_profile_skills_resolve():
    reg = SkillRegistry()
    reg.reload()
    profiles_dir = _repo_root() / "config_std" / "profiles"
    assert profiles_dir.is_dir(), f"missing {profiles_dir}"
    for path in sorted(profiles_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for skill in data.get("skills") or []:
            if skill == "artifact_protocol":
                assert _artifact_skill_loaded(reg), (
                    "artifact_protocol skill file must exist in config_std/skills"
                )
                continue
            assert reg.get_skill_full(skill), (
                f"{path.name} references missing skill {skill!r}"
            )
