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
