"""
Install MCP server from curated connector catalog (no marketplace re-search).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

import yaml

from .mcp_connector_catalog import _connector_by_id, load_mcp_connector_catalog
from .mcp_integration_sync import sync_mcp_server_config_from_registry
from .mcp_manager import mcp_manager


def _slug_from_connector(connector: Dict[str, Any]) -> str:
    hints = connector.get("mcp_name_hints")
    if isinstance(hints, list) and hints:
        raw = str(hints[0])
    else:
        raw = str(connector.get("id") or "mcp")
    slug = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    return slug or "mcp_server"


def _parse_example_registry_block(block: str) -> Dict[str, Any]:
    """Estrae config da snippet YAML commentato nel catalogo."""
    if not block or not str(block).strip():
        return {}
    lines: list[str] = []
    for line in str(block).splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            s = s.lstrip("#").strip()
        if s:
            lines.append(s)
    if not lines:
        return {}
    text = "\n".join(lines)
    try:
        data = yaml.safe_load(text)
    except Exception:
        return {}
    if isinstance(data, dict):
        if len(data) == 1:
            val = next(iter(data.values()))
            if isinstance(val, dict):
                return val
        return {k: v for k, v in data.items() if not str(k).startswith("#")}
    return {}


def _default_registry_config(connector: Dict[str, Any], slug: str) -> Dict[str, Any]:
    cid = str(connector.get("id") or slug)
    pkg: Optional[str] = None
    for line in (connector.get("example_registry_block") or "").splitlines():
        if "@" in line and ("npx" in line.lower() or "-y" in line):
            m = re.search(r"@[\w./-]+", line)
            if m:
                pkg = m.group(0)
                break
    env: Dict[str, str] = {}
    for key in connector.get("required_env") or []:
        if isinstance(key, str) and key.strip():
            env[key.strip()] = f"${{{key.strip()}}}"
    for key in connector.get("optional_env") or []:
        if isinstance(key, str) and key.strip() and key.strip() not in env:
            k = key.strip()
            if k == "CLICKUP_MCP_MODE":
                env[k] = "read-minimal"
            else:
                env[k] = f"${{{k}}}"
    cfg: Dict[str, Any] = {
        "command": "npx",
        "args": ["-y", pkg] if pkg else ["-y", f"@{cid}-mcp"],
        "aion_connector_id": cid,
        "env": env,
        "description": (connector.get("description") or "")[:2000],
    }
    return cfg


def build_registry_config_for_connector(
    connector: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    slug = _slug_from_connector(connector)
    parsed = _parse_example_registry_block(
        connector.get("example_registry_block") or ""
    )
    if parsed.get("command") or parsed.get("args"):
        cfg = dict(parsed)
    else:
        cfg = _default_registry_config(connector, slug)
    cfg["aion_connector_id"] = str(
        connector.get("id") or cfg.get("aion_connector_id") or slug
    )
    if connector.get("description") and not cfg.get("description"):
        cfg["description"] = str(connector.get("description"))[:2000]
    return slug, cfg


async def install_mcp_from_catalog(connector_id: str) -> Dict[str, Any]:
    """Registra server da catalogo, sync policy DB, ritorna preview."""
    catalog = load_mcp_connector_catalog()
    connector = _connector_by_id(catalog, connector_id)
    if not connector:
        return {"ok": False, "error": f"Connector '{connector_id}' not in catalog"}

    slug, cfg = build_registry_config_for_connector(connector)
    mcp_manager.load_registry()
    if slug in mcp_manager._registry and mcp_manager._registry.get(slug, {}).get(
        "is_base"
    ):
        return {"ok": False, "error": f"Cannot overwrite built-in server '{slug}'"}

    mcp_manager._registry_local[slug] = cfg
    mcp_manager._rebuild_merged()
    mcp_manager.save_registry()

    row = await sync_mcp_server_config_from_registry(slug)
    from .mcp_integration_sync import build_integration_preview

    preview = build_integration_preview(slug)
    return {
        "ok": True,
        "name": slug,
        "server_slug": slug,
        "connector_id": connector_id,
        "config": cfg,
        "preview": preview,
        "policy_id": row.id if row else None,
    }
