"""Tests for scripts/env_tuning_profiles.py"""

from __future__ import annotations

from pathlib import Path

from scripts.env_tuning_profiles import (
    MNEMOS_MIGRATION_MARKER,
    MEMPALACE_ENV_KEYS,
    apply_env_profile,
    detect_mempalace_legacy,
    is_protected_env_key,
    merge_missing_only,
)


def test_is_protected_sandbox_keys():
    assert is_protected_env_key("AION_SANDBOX_BACKEND")
    assert is_protected_env_key("AION_PODMAN_SOCKET")
    assert not is_protected_env_key("AION_TOOL_RESULT_FORMAT")


def test_detect_mempalace_legacy_from_env(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AION_MEMPALACE_NAV_ENABLED=1\n", encoding="utf-8")
    assert detect_mempalace_legacy(env, tmp_path) is True


def test_detect_mempalace_skips_after_migration_marker(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        f"AION_MEMPALACE_NAV_ENABLED=1\n{MNEMOS_MIGRATION_MARKER}=mnemos\n",
        encoding="utf-8",
    )
    assert detect_mempalace_legacy(env, tmp_path) is False


def test_apply_env_profile_removes_mempalace_and_sets_mnemos(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "AION_MEMPALACE_NAV_ENABLED=1\nAION_API_URL=http://llm.local\n",
        encoding="utf-8",
    )
    result = apply_env_profile(
        env,
        set_values={
            MNEMOS_MIGRATION_MARKER: "mnemos",
            "AION_MNEMOS_RECALL_LIMIT": "10",
            "AION_API_URL": "should-not-overwrite",
        },
        remove_keys=MEMPALACE_ENV_KEYS,
        dry_run=False,
        skip_protected=True,
    )
    text = env.read_text(encoding="utf-8")
    assert "AION_MEMPALACE_NAV_ENABLED" not in text
    assert f"{MNEMOS_MIGRATION_MARKER}=mnemos" in text
    assert "AION_MNEMOS_RECALL_LIMIT=10" in text
    assert "AION_API_URL=http://llm.local" in text
    assert "should-not-overwrite" not in text
    assert "AION_MEMPALACE_NAV_ENABLED" in result["removed"]


def test_merge_missing_only(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("AION_HARNESS_V2_TURN=1\n", encoding="utf-8")
    missing = merge_missing_only(
        env, {"AION_HARNESS_V2_TURN": "1", "AION_HARNESS_V2_TOOLS": "1"}
    )
    assert missing == {"AION_HARNESS_V2_TOOLS": "1"}
