"""Tests for merge_mcp_registry_from_std.py."""

from __future__ import annotations

import yaml

from scripts.merge_mcp_registry_from_std import merge_mcp_registry_from_std


def test_merge_adds_missing_slug(tmp_path):
    std_dir = tmp_path / "config_std"
    cfg_dir = tmp_path / "config"
    std_dir.mkdir()
    cfg_dir.mkdir()
    (std_dir / "mcp_registry.yaml").write_text(
        yaml.safe_dump(
            {
                "alpha": {"command": "python", "args": ["-u", "alpha/server.py"]},
                "beta": {"command": "python", "args": ["-u", "beta/server.py"]},
            }
        ),
        encoding="utf-8",
    )
    (cfg_dir / "mcp_registry.yaml").write_text(
        yaml.safe_dump(
            {"alpha": {"command": "python", "args": ["-u", "alpha/server.py"]}}
        ),
        encoding="utf-8",
    )

    added = merge_mcp_registry_from_std(root=tmp_path)
    assert added == ["beta"]

    merged = yaml.safe_load((cfg_dir / "mcp_registry.yaml").read_text(encoding="utf-8"))
    assert "beta" in merged
    assert "alpha" in merged

    assert merge_mcp_registry_from_std(root=tmp_path) == []


def test_merge_removes_retired_slug_and_keeps_installed(tmp_path):
    std_dir = tmp_path / "config_std"
    cfg_dir = tmp_path / "config"
    std_dir.mkdir()
    cfg_dir.mkdir()
    (std_dir / "mcp_registry.yaml").write_text(
        "geocoding:\n  type: stdio\n  command: uv\n",
        encoding="utf-8",
    )
    (cfg_dir / "mcp_registry.yaml").write_text(
        "mempalace:\n  type: stdio\n  command: old\n"
        "geocoding:\n  type: stdio\n  command: uv\n",
        encoding="utf-8",
    )
    merge_mcp_registry_from_std(root=tmp_path, dry_run=False)
    text = (cfg_dir / "mcp_registry.yaml").read_text(encoding="utf-8")
    assert "mempalace" not in text
    assert "geocoding" in text


def test_merge_turns_off_skill_write_default(tmp_path):
    std_dir = tmp_path / "config_std"
    cfg_dir = tmp_path / "config"
    std_dir.mkdir()
    cfg_dir.mkdir()
    (std_dir / "mcp_registry.yaml").write_text(
        "skills_hub:\n  command: python\n  env:\n    AION_SKILL_WRITE_ENABLED: '0'\n",
        encoding="utf-8",
    )
    (cfg_dir / "mcp_registry.yaml").write_text(
        "skills_hub:\n  command: python\n  env:\n    AION_SKILL_WRITE_ENABLED: '1'\n"
        "geocoding:\n  command: uv\n",
        encoding="utf-8",
    )
    assert merge_mcp_registry_from_std(root=tmp_path) == []
    merged = yaml.safe_load((cfg_dir / "mcp_registry.yaml").read_text(encoding="utf-8"))
    assert merged["skills_hub"]["env"]["AION_SKILL_WRITE_ENABLED"] == "0"
    assert "geocoding" in merged
    assert merge_mcp_registry_from_std(root=tmp_path) == []
