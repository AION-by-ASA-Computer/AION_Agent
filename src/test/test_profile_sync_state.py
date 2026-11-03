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
    # A customized hash must never become the baseline, or the next boot overwrites it.
    state = load_profile_sync_state(cfg)
    assert "profiles/aion_std.yaml" not in state


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


def _setup(tmp_path: Path, std_text: str) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    profiles_std = root / "config_std" / "profiles"
    profiles_cfg = root / "config" / "profiles"
    profiles_std.mkdir(parents=True)
    profiles_cfg.mkdir(parents=True)
    (profiles_std / "aion_std.yaml").write_text(std_text, encoding="utf-8")
    return root, profiles_std, profiles_cfg


def test_admin_save_survives_repeated_boots(tmp_path: Path):
    """Regression: admin edit was recorded as baseline and overwritten on the next boot."""
    from src.runtime.profile_sync_state import record_profile_after_admin_save

    root, _std, profiles_cfg = _setup(tmp_path, _profile_yaml("AION", "from std"))
    cfg = root / "config"
    sync_config(force=True, profiles_only=True, root=root)  # first boot

    target = profiles_cfg / "aion_std.yaml"
    target.write_text(_profile_yaml("AION", "my admin edit"), encoding="utf-8")
    record_profile_after_admin_save(target, cfg)

    for _ in range(3):  # container restarts (e.g. after saving LLM settings)
        sync_config(force=True, profiles_only=True, root=root)
        assert "my admin edit" in target.read_text(encoding="utf-8")


def test_customized_profile_without_admin_hook_survives_repeated_boots(tmp_path: Path):
    root, _std, profiles_cfg = _setup(tmp_path, _profile_yaml("AION", "from std"))
    sync_config(force=True, profiles_only=True, root=root)

    target = profiles_cfg / "aion_std.yaml"
    target.write_text(_profile_yaml("AION", "manual edit"), encoding="utf-8")
    for _ in range(3):
        sync_config(force=True, profiles_only=True, root=root)
        assert "manual edit" in target.read_text(encoding="utf-8")


def test_profile_reverted_to_std_follows_template_updates(tmp_path: Path):
    from src.runtime.profile_sync_state import record_profile_after_admin_save

    std_v1 = _profile_yaml("AION", "from std v1")
    root, profiles_std, profiles_cfg = _setup(tmp_path, std_v1)
    cfg = root / "config"
    sync_config(force=True, profiles_only=True, root=root)

    target = profiles_cfg / "aion_std.yaml"
    target.write_text(_profile_yaml("AION", "edit"), encoding="utf-8")
    record_profile_after_admin_save(target, cfg)
    target.write_text(std_v1, encoding="utf-8")  # admin reverts to the template
    sync_config(force=True, profiles_only=True, root=root)

    (profiles_std / "aion_std.yaml").write_text(
        _profile_yaml("AION", "from std v2"), encoding="utf-8"
    )
    sync_config(force=True, profiles_only=True, root=root)
    assert "from std v2" in target.read_text(encoding="utf-8")
