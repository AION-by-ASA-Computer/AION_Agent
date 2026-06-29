"""Track profile YAML hashes so ``sync_config --force`` can skip local customizations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Tuple

_STATE_REL = Path("profiles") / ".aion-sync-state.json"


def _config_dir(config_root: Path | None = None) -> Path:
    if config_root is not None:
        return config_root
    return Path(__file__).resolve().parent.parent.parent / "config"


def _state_path(config_root: Path | None = None) -> Path:
    return _config_dir(config_root) / _STATE_REL


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_profile_sync_state(config_root: Path | None = None) -> Dict[str, str]:
    path = _state_path(config_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles = data.get("profiles") or {}
        return {k: v for k, v in profiles.items() if isinstance(k, str) and isinstance(v, str)}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def save_profile_sync_state(state: Dict[str, str], config_root: Path | None = None) -> None:
    path = _state_path(config_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"profiles": dict(sorted(state.items()))}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def profile_rel_key(rel_path: Path) -> str | None:
    if len(rel_path.parts) >= 2 and rel_path.parts[0] == "profiles" and rel_path.suffix == ".yaml":
        return rel_path.as_posix()
    return None


def should_preserve_profile_on_force(
    target: Path,
    source: Path,
    state: Dict[str, str],
    rel_key: str,
) -> Tuple[bool, str]:
    """Return (preserve, reason). May update *state* in place."""
    if not target.is_file():
        return False, "new"
    target_hash = file_sha256(target)
    source_hash = file_sha256(source)
    if target_hash == source_hash:
        state[rel_key] = target_hash
        return False, "identical"
    recorded = state.get(rel_key)
    if recorded is None:
        state[rel_key] = target_hash
        return True, "customized (no prior sync state)"
    if target_hash == recorded:
        return False, "unchanged since last sync"
    state[rel_key] = target_hash
    return True, "customized"


def record_profile_after_sync(target: Path, state: Dict[str, str], rel_key: str) -> None:
    if target.is_file():
        state[rel_key] = file_sha256(target)


def record_profile_after_admin_save(yaml_path: Path, config_root: Path | None = None) -> None:
    rel_key = profile_rel_key(Path("profiles") / yaml_path.name)
    if not rel_key or not yaml_path.is_file():
        return
    state = load_profile_sync_state(config_root)
    state[rel_key] = file_sha256(yaml_path)
    save_profile_sync_state(state, config_root)
