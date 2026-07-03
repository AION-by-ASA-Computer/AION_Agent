"""Full system-prompt regression suite (skills, protocols, language rules)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.agent_profile import AgentProfile, profile_manager
from src.runtime.skill_discovery_nudge import build_skill_discovery_nudge
from src.runtime.user_language import build_ui_language_prompt_section
from src.skill_registry import SkillRegistry

_REPO = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO / "config_std" / "skills"

# Heuristic: Italian prose in skill bodies (not filenames / examples).
_ITALIAN_SKILL_MARKERS = re.compile(
    r"\b(scrivi il|non è un tool|devi |sempre |vedi sotto|Cosa fare|"
    r"Il file si crea|procedi comunque|nella risposta)\b",
    re.I,
)


@pytest.fixture(autouse=True)
def prompt_env(monkeypatch):
    monkeypatch.setenv("AION_SKILL_SYSTEM_PROMPT_MODE", "index")
    monkeypatch.setenv("AION_SOUL_MEMORY_USER_SPLIT", "0")


def _aion_std_prompt() -> str:
    profile_manager.load_all()
    p = profile_manager.get_profile("aion_std")
    assert p is not None
    return p.generate_system_prompt()


def test_aion_std_inlines_critical_protocol_skills():
    body = _aion_std_prompt()
    for slug in ("core_protocol", "artifact_protocol", "agent_db_protocol"):
        assert f"### Protocol rules ({slug})" in body


def test_aion_std_tool_first_file_delivery():
    body = _aion_std_prompt()
    assert "sandbox_write_workspace_file" in body
    assert "tool-first" in body.lower() or "filesystem tools" in body.lower()
    # Legacy artifact stream is secondary, not primary
    lower = body.lower()
    assert "write the file in your chat reply" not in lower or "legacy" in lower


def test_aion_std_model_prompt_fragment_optional():
    profile_manager.load_all()
    p = profile_manager.get_profile("aion_std")
    body = p.generate_system_prompt(model_id="gpt-5")
    assert "sandbox_apply_patch" in body or "apply_patch" in body


def test_skill_discovery_nudge_write_tool_first():
    nudge = build_skill_discovery_nudge("create a word doc")
    assert "sandbox_write_workspace_file" in nudge
    assert "aion_artifact" in nudge
    assert "phantom" in nudge.lower() or "not" in nudge.lower()


def test_aion_std_thinking_english_rule():
    body = _aion_std_prompt()
    assert (
        "thinking/reasoning blocks" in body.lower()
        or "internal thinking" in body.lower()
    )
    assert "english" in body.lower()


def test_aion_std_skill_index_lists_artifact_protocol():
    body = _aion_std_prompt()
    assert "**`artifact_protocol`**" in body or "artifact_protocol" in body


def test_ui_language_section_user_locale_english_thinking():
    it_section = build_ui_language_prompt_section("it")
    assert "thinking/reasoning blocks must stay in English" in it_section
    en_section = build_ui_language_prompt_section("en")
    assert "thinking/reasoning blocks must stay in English" in en_section


def test_config_std_critical_skill_files_english_prose():
    """Curated skills referenced in prompts must not contain Italian instruction prose."""
    reg = SkillRegistry()
    reg.reload()
    for path in sorted(_SKILLS_DIR.glob("*.md")):
        name = path.stem
        if name not in (
            "core_protocol",
            "artifact_protocol",
            "filesystem_tools_protocol",
        ):
            continue
        full = reg.get_skill_full(name) or path.read_text(encoding="utf-8")
        # Strip frontmatter
        body = full.split("---", 2)[-1] if full.startswith("---") else full
        assert not _ITALIAN_SKILL_MARKERS.search(body), (
            f"{name}.md contains Italian instruction prose"
        )


def test_artifact_protocol_skill_loaded_and_english():
    reg = SkillRegistry()
    reg.reload()
    body = reg.get_skill_full("artifact_protocol")
    assert body
    assert "sandbox_write_workspace_file" in body
    assert "phantom" in body.lower() or "aion_artifact" in body.lower()


def test_minimal_profile_always_inlines_core_even_without_critical_list():
    p = AgentProfile(
        name="T",
        description="",
        instructions="Base instructions.",
        skills=["infra_audit"],
        critical_skills=[],
        slug="t",
    )
    body = p.generate_system_prompt()
    assert "Base instructions." in body
    assert "### Protocol rules (core_protocol)" in body
    assert "sandbox_write_workspace_file" in body
