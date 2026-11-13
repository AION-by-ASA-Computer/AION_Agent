"""record_profile_after_admin_save: only profiles directly inside <config>/profiles are tracked.

Covers the path-containment guard added for CodeQL py/path-injection (alert #674):
paths outside the synced profiles directory are ignored without touching state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime.profile_sync_state import (
    load_profile_sync_state,
    record_profile_after_admin_save,
    save_profile_sync_state,
)


@pytest.fixture
def config_root(tmp_path: Path) -> Path:
    """A config dir with one synced profile that has a recorded baseline hash."""
    root = tmp_path / "config"
    (root / "profiles").mkdir(parents=True)
    (root / "profiles" / "sre.yaml").write_text("name: SRE\n", encoding="utf-8")
    save_profile_sync_state({"profiles/sre.yaml": "baseline"}, root)
    return root


def test_admin_save_inside_profiles_drops_baseline(config_root: Path) -> None:
    """A save in <config>/profiles drops the baseline so sync --force preserves it."""
    record_profile_after_admin_save(config_root / "profiles" / "sre.yaml", config_root)
    assert "profiles/sre.yaml" not in load_profile_sync_state(config_root)


@pytest.mark.parametrize(
    "rel",
    [
        # All relative to <config>/profiles.
        "../sre.yaml",  # traversal out of profiles/ to a same-named file
        "../../overlay/sre.yaml",  # separate AION_PROFILES_WRITE_DIR overlay
        "nested/sre.yaml",  # sub-directory is not a profile
    ],
)
def test_admin_save_outside_profiles_is_ignored(config_root: Path, rel: str) -> None:
    """Paths outside <config>/profiles (or nested in it) leave the sync state untouched."""
    target = config_root / "profiles" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("name: X\n", encoding="utf-8")
    record_profile_after_admin_save(target, config_root)
    assert load_profile_sync_state(config_root) == {"profiles/sre.yaml": "baseline"}
