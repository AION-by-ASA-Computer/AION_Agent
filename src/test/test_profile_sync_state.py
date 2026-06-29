"""sync_config preserves customized profile YAML on --force."""
import textwrap
from pathlib import Path

from scripts.sync_config import sync_config
from src.runtime.profile_sync_state import load_profile_sync_state


def _profile_yaml(name: str, instructions: str) -> str:
    return textwrap.dedent(
        f"""
        name: {name}
        description: d
        instructions: {instructions}
        skills: []
        mcp_servers: []
        """
    )


def test_force_sync_preserves_customized_profile(tmp_path: Path):
    root = tmp_path / "repo"
    std = root / "config_std"
    cfg = root / "config"
    profiles_std = std / "profiles"
    profiles_cfg = cfg / "profiles"
    profiles_std.mkdir(parents=True)
    profiles_cfg.mkdir(parents=True)

    (profiles_std / "aion_std.yaml").write_text(
        _profile_yaml("AION", "from std v2"), encoding="utf-8"
    )
    (profiles_cfg / "aion_std.yaml").write_text(
        _profile_yaml("AION", "my admin edit"), encoding="utf-8"
    )

    sync_config(force=True, profiles_only=True, root=root)

    content = (profiles_cfg / "aion_std.yaml").read_text(encoding="utf-8")
    assert "my admin edit" in content
    assert "from std v2" not in content
    state = load_profile_sync_state(cfg)
    assert "profiles/aion_std.yaml" in state


def test_force_sync_updates_unchanged_profile(tmp_path: Path):
    root = tmp_path / "repo"
    std = root / "config_std"
    cfg = root / "config"
    profiles_std = std / "profiles"
    profiles_cfg = cfg / "profiles"
    profiles_std.mkdir(parents=True)
    profiles_cfg.mkdir(parents=True)

    old = _profile_yaml("AION", "from std v1")
    new = _profile_yaml("AION", "from std v2")
    (profiles_cfg / "aion_std.yaml").write_text(old, encoding="utf-8")
    (profiles_std / "aion_std.yaml").write_text(old, encoding="utf-8")

    sync_config(force=True, profiles_only=True, root=root)

    (profiles_std / "aion_std.yaml").write_text(new, encoding="utf-8")
    sync_config(force=True, profiles_only=True, root=root)

    content = (profiles_cfg / "aion_std.yaml").read_text(encoding="utf-8")
    assert "from std v2" in content
