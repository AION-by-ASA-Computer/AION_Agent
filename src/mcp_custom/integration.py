"""Credential policy of custom servers, read from their manifest.

For catalog/marketplace servers AION *infers* the credential mode and schema
(catalog rows, README/env discovery). For custom servers the manifest already
declares them, so the existing discovery, preview and boot-sync code ask this
module first. Without it the boot sync (``sync_all_mcp_server_configs_from_registry``)
would overwrite the declared mode at every restart.

Used by ``src/mcp_credential_discovery.py``, ``src/mcp_integration_sync.py`` and
the admin endpoints that must not let the UI change a manifest-owned field.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .paths import is_custom_config


def custom_meta(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The ``aion_custom`` block of a registry entry, or None for other servers."""
    return config["aion_custom"] if is_custom_config(config) else None


def custom_credential_mode(config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Declared credential mode (``none``/``org_shared``/``per_user``) or None."""
    meta = custom_meta(config)
    if meta is None:
        return None
    mode = str(meta.get("credential_mode") or "none")
    return mode if mode in ("none", "org_shared", "per_user") else "none"


def custom_credential_schema(config: Optional[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """Declared credential schema (list of fields) or None for non-custom servers."""
    meta = custom_meta(config)
    if meta is None:
        return None
    schema = meta.get("credential_schema")
    return [dict(f) for f in schema if isinstance(f, dict)] if isinstance(schema, list) else []


def custom_secret_keys(config: Optional[Dict[str, Any]]) -> List[str]:
    """Credential keys declared ``secret: true`` (stored encrypted by the Hub)."""
    return [str(f["key"]) for f in custom_credential_schema(config) or [] if f.get("is_secret", True) and f.get("key")]


def custom_display_meta(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Display name/description/category for ``McpServerConfig`` rows of custom servers."""
    meta = custom_meta(config)
    if meta is None:
        return None
    return {
        "display_name": str(meta.get("name") or ""),
        "description": (config or {}).get("description"),
        "category": "custom",
        "aion_connector_id": None,
    }
