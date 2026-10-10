"""Cache of MCP list_tools payloads shared across chat sessions.

Session-scoped servers stay out of this cache: their workers are per chat.
The cache stores schemas only. Wrappers are rebuilt with the current session_id.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aion.mcp_tool_catalog")

CatalogKey = Tuple[str, str, str, str]


class McpToolCatalog:
    def __init__(self) -> None:
        self._entries: Dict[CatalogKey, List[Dict[str, Any]]] = {}

    @staticmethod
    def registry_fingerprint(server_config: Optional[Dict[str, Any]]) -> str:
        cfg = server_config or {}
        blob = {
            "type": cfg.get("type") or "stdio",
            "command": cfg.get("command"),
            "args": cfg.get("args"),
            "url": cfg.get("url"),
        }
        raw = json.dumps(blob, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def key(
        self,
        *,
        user_id: str,
        tenant_id: str,
        server_name: str,
        server_config: Optional[Dict[str, Any]],
    ) -> CatalogKey:
        return (
            (user_id or "default").strip() or "default",
            (tenant_id or "default").strip() or "default",
            server_name,
            self.registry_fingerprint(server_config),
        )

    def get(self, key: CatalogKey) -> Optional[List[Dict[str, Any]]]:
        hit = self._entries.get(key)
        if hit is None:
            return None
        return list(hit)

    def put(self, key: CatalogKey, specs: List[Dict[str, Any]]) -> None:
        self._entries[key] = list(specs)

    def clear(self) -> None:
        self._entries.clear()


mcp_tool_catalog = McpToolCatalog()


def clear_mcp_tool_catalog() -> None:
    mcp_tool_catalog.clear()
