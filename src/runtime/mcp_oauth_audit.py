"""Audit log for MCP OAuth events (dynamic client registration, refresh failures)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.mcp_oauth_audit")


def _audit_path() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root / "mcp_oauth_audit.jsonl"


def append_mcp_oauth_audit(event: str, payload: Dict[str, Any]) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("mcp oauth audit log failed: %s", exc)


def log_dynamic_client_registration(
    *,
    server_slug: str,
    registration_endpoint: str,
    client_id: Optional[str] = None,
) -> None:
    append_mcp_oauth_audit(
        "dynamic_client_registration",
        {
            "server_slug": server_slug,
            "registration_endpoint": registration_endpoint,
            "client_id": client_id,
        },
    )
