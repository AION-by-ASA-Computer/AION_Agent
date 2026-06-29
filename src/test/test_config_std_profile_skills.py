"""config_std profiles must reference skill slugs that SkillRegistry actually loads."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.skill_registry import SkillRegistry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _artifact_variant_loaded(reg: SkillRegistry) -> bool:
    return any(
        reg.get_skill_full(n)
        for n in (
            "artifact_protocol_xml",
            "artifact_protocol_markdown",
            "artifact_protocol_tool",
        )
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
                assert _artifact_variant_loaded(reg), (
                    "artifact_protocol requires at least one artifact_protocol_* skill"
                )
                continue
            assert reg.get_skill_full(skill), (
                f"{path.name} references missing skill {skill!r}"
            )
