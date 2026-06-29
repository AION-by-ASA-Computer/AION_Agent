"""Load/save MCP registry documents (flat YAML or standard JSON ``mcpServers``)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger("aion.mcp_registry_io")

_RESERVED_TOP_KEYS = frozenset(
    {"_removed", "$schema", "mcpServers", "servers", "inputs", "mcp"}
)


def flatten_registry_document(data: Any) -> Dict[str, Any]:
    """
    Normalize registry payload to flat server map (AION internal shape).

    Supports:
    - Flat YAML (``prometheus: {command: ...}``)
    - Claude / Cursor / Claude Code: ``{"mcpServers": {...}}``
    - VS Code Copilot: ``{"servers": {...}}`` (optional ``"mcp"`` wrapper)
    """
    if not isinstance(data, dict):
        return {}

    if "mcpServers" in data:
        raw = data["mcpServers"]
        if isinstance(raw, dict):
            return {k: v for k, v in raw.items() if isinstance(v, dict)}

    if "mcp" in data and isinstance(data["mcp"], dict):
        inner = data["mcp"].get("servers")
        if isinstance(inner, dict):
            return {k: v for k, v in inner.items() if isinstance(v, dict)}

    if "servers" in data and isinstance(data["servers"], dict):
        return {k: v for k, v in data["servers"].items() if isinstance(v, dict)}

    return {
        k: v
        for k, v in data.items()
        if k not in _RESERVED_TOP_KEYS and isinstance(v, dict)
    }


def companion_json_path(registry_path: str) -> str:
    """``config/mcp_registry.yaml`` → ``config/mcp_registry.json``."""
    p = Path(registry_path)
    return str(p.with_suffix(".json"))


def load_registry_file(path: str) -> Dict[str, Any]:
    """Load YAML or JSON registry file; returns flat server map (+ ``_removed`` if set)."""
    p = Path(path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        if p.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text) or {}
    except Exception as exc:
        logger.error("Error loading MCP registry %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    flat = flatten_registry_document(data)
    removed = data.get("_removed")
    if isinstance(removed, list):
        flat["_removed"] = removed
    return flat


def dump_registry_json(servers: Dict[str, Any], *, indent: int = 2) -> str:
    """Serialize to market-standard ``mcpServers`` JSON."""
    body = {k: v for k, v in servers.items() if k != "_removed"}
    payload: Dict[str, Any] = {"mcpServers": body}
    if "_removed" in servers:
        payload["_removed"] = servers["_removed"]
    return json.dumps(payload, indent=indent, ensure_ascii=False) + "\n"
