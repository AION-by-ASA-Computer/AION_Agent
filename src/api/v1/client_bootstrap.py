"""``GET /v1/client/bootstrap``: sync di profili, skill e MCP per i client Enterprise.

Contratto: aion-cowork/docs/enterprise-api-contract.md (Fase 2). Un solo documento per
utente con ETag/If-None-Match. Mai esposti segreti, ``command/args/env/url`` del registro
dei server non dichiarati esplicitamente dall'admin con un blocco ``client:``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.data.engine import get_async_session_maker
from src.data.models import McpServerConfig, UserProfileAccess

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/client", tags=["v1-client"])

SKILL_MAX_BYTES = 256 * 1024
DEFAULT_SYNC_INTERVAL_SEC = 900
MIN_SYNC_INTERVAL_SEC = 60

# Stati skill NON pubblicabili verso i client.
_UNPUBLISHABLE_SKILL_STATUS = frozenset(
    {"draft", "pending", "rejected", "archived", "deprecated", "disabled"}
)

_EXECUTIONS = frozenset({"client_remote", "client_local"})
_AUTHS = frozenset({"none", "aion_token"})
_TRANSPORTS = frozenset({"sse", "streamable-http", "stdio"})
_REMOTE_TRANSPORTS = frozenset({"sse", "streamable-http"})
_SECRET_KEY_RE = re.compile(r"key|token|secret|password", re.IGNORECASE)


# --- Validazione del blocco `client:` -------------------------------------


def _has_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return "${" in value
    if isinstance(value, dict):
        return any(_has_placeholder(k) or _has_placeholder(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_placeholder(v) for v in value)
    return False


def validate_client_block(block: Any) -> Optional[Dict[str, Any]]:
    """Normalizza un blocco ``client:``; ``None`` se invalido (-> ``server_only``)."""
    if not isinstance(block, dict) or _has_placeholder(block):
        return None
    execution = block.get("execution")
    auth = block.get("auth", "none")
    tr = block.get("transport")
    if execution not in _EXECUTIONS or auth not in _AUTHS or not isinstance(tr, dict):
        return None
    ttype = tr.get("type")
    if ttype not in _TRANSPORTS:
        return None

    transport: Dict[str, Any]
    if ttype in _REMOTE_TRANSPORTS:
        if execution != "client_remote":
            return None
        url = tr.get("url")
        if not isinstance(url, str) or not url.strip():
            return None
        parsed = urlparse(url.strip())
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        transport = {"type": ttype, "url": url.strip()}
    else:
        if execution != "client_local":
            return None
        command = tr.get("command")
        if not isinstance(command, str) or not command.strip():
            return None
        args = tr.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return None
        env = tr.get("env", {})
        if not isinstance(env, dict):
            return None
        for k, v in env.items():
            if not isinstance(k, str) or not isinstance(v, str):
                return None
            if _SECRET_KEY_RE.search(k):
                return None
        transport = {
            "type": "stdio",
            "command": command.strip(),
            "args": list(args),
            "env": dict(env),
        }
    return {"execution": execution, "transport": transport, "auth": auth}


# --- Accesso ai dati (sostituibili nei test) -------------------------------


async def _allowed_profile_slugs(user_row_id: Optional[str]) -> Optional[List[str]]:
    """Slug consentiti all'utente; ``None`` = tutti (nessuna riga o chiamante API key)."""
    if not user_row_id or user_row_id == "default":
        return None
    async with get_async_session_maker()() as session:
        res = await session.execute(
            select(UserProfileAccess.profile_slug).where(
                UserProfileAccess.user_id == user_row_id
            )
        )
        slugs = [r[0] for r in res.all()]
    return slugs or None


async def _enabled_mcp_rows() -> List[Any]:
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.is_enabled_for_users.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


def _registry_slugs() -> set:
    from src.mcp_manager import mcp_manager

    mcp_manager.load_registry()
    return set(mcp_manager._registry.keys())


def _client_block(slug: str) -> Optional[Dict[str, Any]]:
    from src.mcp_manager import mcp_manager

    return mcp_manager.get_client_block(slug)


def _loaded_profiles() -> List[Any]:
    from src.agent_profile import profile_manager

    profile_manager.load_all_if_stale()
    return list(profile_manager._profiles.values())


def _skill_registry():
    from src.skill_registry import skill_registry

    skill_registry.reload_if_stale()
    return skill_registry


# --- Costruzione del documento ---------------------------------------------


def _iso_mtime(path: Optional[Path]) -> Optional[str]:
    try:
        if path is None:
            return None
        ts = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_interval_sec() -> int:
    raw = (os.getenv("AION_CLIENT_SYNC_INTERVAL_SEC") or "").strip()
    try:
        val = int(raw) if raw else DEFAULT_SYNC_INTERVAL_SEC
    except ValueError:
        val = DEFAULT_SYNC_INTERVAL_SEC
    return max(MIN_SYNC_INTERVAL_SEC, val)


def _profile_path(slug: str) -> Optional[Path]:
    try:
        from src.agent_profile import profile_manager

        return profile_manager.profile_yaml_path(slug)
    except Exception:  # noqa: BLE001
        return None


def _build_skills(names: List[str], registry) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name in sorted(set(names)):
        meta = registry.get_meta(name)
        if not meta:
            continue
        status = str(meta.get("status") or "verified").lower()
        if status in _UNPUBLISHABLE_SKILL_STATUS:
            continue
        # Per i package (cartelle) il path caricato e' SKILL.md: solo quello viene inviato.
        path = registry.get_skill_path(name)
        if path is None:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if len(raw) > SKILL_MAX_BYTES:
            logger.warning(
                "client_bootstrap: skill %r omessa (%d byte > %d)",
                name,
                len(raw),
                SKILL_MAX_BYTES,
            )
            continue
        out.append(
            {
                "name": name,
                "description": meta.get("description") or "",
                "tags": list(meta.get("tags") or []),
                "version": meta.get("version", 1),
                "status": meta.get("status", "verified"),
                "content": raw.decode("utf-8", errors="replace"),
                "updated_at": _iso_mtime(path),
            }
        )
    return out


def _build_mcp_server(row: Any) -> Dict[str, Any]:
    slug = row.server_slug
    entry: Dict[str, Any] = {
        "slug": slug,
        "display_name": row.display_name or slug,
    }
    if getattr(row, "description", None):
        entry["description"] = row.description
    if getattr(row, "category", None):
        entry["category"] = row.category

    mode = getattr(row, "credential_mode", None) or "none"
    block = None
    raw_block = _client_block(slug)
    if raw_block is not None:
        if mode == "none":
            block = validate_client_block(raw_block)
        else:
            logger.warning(
                "client_bootstrap: blocco client ignorato per %r (credential_mode=%s)",
                slug,
                mode,
            )
        if block is None:
            logger.warning(
                "client_bootstrap: blocco client non valido per %r, uso server_only",
                slug,
            )
    if block is None:
        entry["execution"] = "server_only"
        entry["auth"] = "none"
        return entry
    entry.update(block)
    return entry


async def build_bootstrap_document(auth: ChatAuthIdentity) -> Dict[str, Any]:
    allowed = await _allowed_profile_slugs(auth.user_row_id)
    profiles = [p for p in _loaded_profiles() if allowed is None or p.slug in allowed]
    profiles.sort(key=lambda p: p.slug)

    registry = _skill_registry()
    resolved = {p.slug: p.resolved_skills() for p in profiles}
    referenced_skills = {n for names in resolved.values() for n in names}
    skills = _build_skills(sorted(referenced_skills), registry)
    skill_names = {s["name"] for s in skills}

    referenced_mcp = {s for p in profiles for s in (p.mcp_servers or [])}
    reg_slugs = _registry_slugs()
    mcp_servers = [
        _build_mcp_server(r)
        for r in sorted(await _enabled_mcp_rows(), key=lambda r: r.server_slug)
        if r.server_slug in reg_slugs and r.server_slug in referenced_mcp
    ]
    mcp_names = {m["slug"] for m in mcp_servers}

    doc_profiles = [
        {
            "slug": p.slug,
            "name": p.name,
            "description": p.description,
            "instructions": p.instructions,
            "max_agent_steps": p.max_agent_steps,
            "skills": [n for n in resolved[p.slug] if n in skill_names],
            "mcp_servers": [s for s in (p.mcp_servers or []) if s in mcp_names],
            "native_tool_groups": list(p.native_tool_groups or []),
            "updated_at": _iso_mtime(_profile_path(p.slug)),
        }
        for p in profiles
    ]
    return {
        "profiles": doc_profiles,
        "skills": skills,
        "mcp_servers": mcp_servers,
        "policy": {"sync_interval_sec": sync_interval_sec()},
    }


def compute_revision(doc: Dict[str, Any]) -> str:
    body = {k: v for k, v in doc.items() if k not in ("revision", "generated_at")}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _etag_matches(header: Optional[str], etag: str) -> bool:
    if not header:
        return False
    for part in header.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("W/"):
            part = part[2:]
        if part == etag:
            return True
    return False


@router.get("/bootstrap")
async def client_bootstrap(
    request: Request,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    doc = await build_bootstrap_document(auth)
    revision = compute_revision(doc)
    etag = f'"{revision}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    body = {
        "revision": revision,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **doc,
    }
    return JSONResponse(content=body, headers=headers)
