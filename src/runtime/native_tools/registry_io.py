"""Caricamento e merge del registry tool nativi (stile MCP registry)."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = __import__("logging").getLogger(__name__)


def _default_registry_path() -> str:
    return os.getenv(
        "AION_NATIVE_TOOL_REGISTRY_PATH",
        os.path.join("config", "native_tool_registry.yaml"),
    )


def _default_local_registry_path(base_path: str) -> str:
    explicit = os.getenv("AION_NATIVE_TOOL_REGISTRY_LOCAL_PATH")
    if explicit:
        return explicit
    d, f = os.path.split(base_path)
    stem, ext = os.path.splitext(f)
    return os.path.join(d or ".", f"{stem}.local{ext}")


def _merge_registries(base: Dict[str, Any], local: Dict[str, Any]) -> Dict[str, Any]:
    """Merge superficiale: chiavi in `local` sovrascrivono `base` (stesso pattern MCP)."""
    base = base or {}
    local = local or {}
    out = copy.deepcopy(base)
    for k, v in local.items():
        out[k] = copy.deepcopy(v)
    return out


def load_merged_native_tool_registry() -> Dict[str, Any]:
    base_path = Path(_default_registry_path())
    if not base_path.is_file():
        logger.warning("Native tool registry missing: %s", base_path)
        return {"bundles": {}}
    with base_path.open(encoding="utf-8") as f:
        base = yaml.safe_load(f) or {}
    local_path = Path(_default_local_registry_path(str(base_path)))
    if not local_path.is_file():
        return base
    with local_path.open(encoding="utf-8") as f:
        local = yaml.safe_load(f) or {}
    return _merge_registries(base, local)


def get_bundle(bundle_id: str) -> Optional[Dict[str, Any]]:
    reg = load_merged_native_tool_registry()
    bundles = reg.get("bundles") or {}
    b = bundles.get(bundle_id)
    if not isinstance(b, dict):
        return None
    return b
