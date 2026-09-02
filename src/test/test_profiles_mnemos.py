"""Regression: default-facing profiles must declare Mnemos native tools."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROFILES = ROOT / "config_std" / "profiles"

# Profiles intentionally without Mnemos (narrow scope).
MNEMOS_EXEMPT = frozenset(
    {
        "document_extractor.yaml",
        "graphic_designer.yaml",
        "coding_workspace.yaml",
        "data_agent.yaml",
        "mcp_integration_advisor.yaml",
    }
)


def _load(name: str) -> dict:
    return yaml.safe_load((PROFILES / name).read_text(encoding="utf-8")) or {}


def test_generic_assistant_has_mnemos_native_tools():
    data = _load("generic_assistant.yaml")
    groups = data.get("native_tool_groups") or []
    assert "mnemos" in groups, "generic_assistant must list native_tool_groups: mnemos"
    assert "memory_protocol" in (data.get("skills") or [])
    assert "memory_protocol" in (data.get("critical_skills") or [])


def test_default_assistant_profiles_include_mnemos():
    for path in sorted(PROFILES.glob("*.yaml")):
        if path.name in MNEMOS_EXEMPT:
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        groups = data.get("native_tool_groups") or []
        assert "mnemos" in groups, f"{path.name} missing native_tool_groups mnemos"
