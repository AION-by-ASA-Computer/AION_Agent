"""User-facing MCP integrations (chat JWT, not X-API-Key)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.data.engine import get_async_session_maker
from src.data.models import McpServerConfig
from src.identity import sanitize_user_id
from src.runtime.credential_store import (
    delete_credential,
    persist_oauth_token_response,
    set_credential,
    user_credentials_enabled,
)
from src.runtime.mcp_integration_helpers import (
    batch_list_credentials_hints,
    credentials_feature_enabled,
    get_user_mcp_preference_map,
    integration_row_to_public_dict,
    list_pending_for_profile,
    set_user_mcp_preference,
)

router = APIRouter(prefix="/integrations", tags=["mcp-integrations"])


def _tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


def _is_loopback_host_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def _chat_base_url(request: Optional[Request] = None) -> str:
    """
    Browser-facing chat-ui base URL for OAuth return redirects.

    In Docker prod ``AION_CHAT_URL=http://localhost:8003`` is wrong for the user's
    browser — derive from ``AION_OAUTH_REDIRECT_BASE_URL`` / proxy headers when set.
    """
    explicit = (os.getenv("AION_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit) and not _is_loopback_host_url(explicit):
        return explicit

    public_chat = (os.getenv("AION_PUBLIC_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(public_chat):
        return public_chat

    api_base = _oauth_redirect_api_base(request)
    if _is_absolute_http_url(api_base):
        low = api_base.rstrip("/").lower()
        if low.endswith("/api"):
            return api_base.rstrip("/")[:-4]
        return api_base.rstrip("/")

    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
        scheme = fwd_proto or request.url.scheme
        if host and not host.startswith("backend:"):
            return f"{scheme}://{host}".rstrip("/")

    domain = (os.getenv("DOMAIN") or "").strip()
    if domain and domain not in (":80", "http://:80"):
        host = domain.lstrip("http://").lstrip("https://").strip("/")
        if host and not host.startswith(":"):
            scheme = (
                "https" if (os.getenv("LETS_ENCRYPT_EMAIL") or "").strip() else "http"
            )
            return f"{scheme}://{host}"

    if _is_absolute_http_url(explicit):
        return explicit
    return "http://localhost:8003"


def _credential_user_id(auth: ChatAuthIdentity) -> str:
    raw = (auth.identifier or auth.user_row_id or "").strip()
    return sanitize_user_id(raw if raw else None)


def _require_credentials_enabled() -> None:
    if not user_credentials_enabled():
        raise HTTPException(
            status_code=501,
            detail="User MCP credentials not enabled (set AION_MCP_USER_CREDENTIALS=1)",
        )


def _require_identity_for_mutation(auth: ChatAuthIdentity) -> None:
    if auth.via == "anonymous" or not (auth.identifier or auth.user_row_id):
        raise HTTPException(
            status_code=403,
            detail="Authentication required to manage MCP credentials.",
        )


# ---------------------------------------------------------------------------
# Response-level TTL cache for list_available_integrations.
# Keyed by user_id so each user gets their own cache entry.
# TTL defaults to 30 s, configurable via AION_INTEGRATIONS_LIST_TTL.
# ---------------------------------------------------------------------------
_INTEGRATIONS_CACHE: Dict[str, tuple[float, Dict[str, Any]]] = {}
_INTEGRATIONS_CACHE_TTL: int = int(os.environ.get("AION_INTEGRATIONS_LIST_TTL", "30"))


def clear_integrations_cache() -> None:
    """Invalidate the integrations list cache after mutations."""
    _INTEGRATIONS_CACHE.clear()


@router.get("/status")
async def integrations_status() -> Dict[str, Any]:
    return {
        "credentials_feature_enabled": credentials_feature_enabled(),
        "hint": (
            None
            if credentials_feature_enabled()
            else "Impostare AION_MCP_USER_CREDENTIALS=1 e AION_CREDENTIAL_ENCRYPTION_KEY sul backend."
        ),
    }


@router.get("")
async def list_available_integrations(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    user_id = _credential_user_id(auth)
    tenant = _tenant_id()
    anonymous = auth.via == "anonymous" or not (auth.identifier or auth.user_row_id)

    # Response-level TTL cache (keyed by user_id; anonymous callers bypass)
    if not anonymous:
        cache_key = f"{user_id}:{tenant}"
        now = time.monotonic()
        cached = _INTEGRATIONS_CACHE.get(cache_key)
        if cached is not None:
            ts, resp = cached
            if now - ts < _INTEGRATIONS_CACHE_TTL:
                return resp
        elif _INTEGRATIONS_CACHE:
            # Evict stale entries on access
            _INTEGRATIONS_CACHE.clear()

    # Carica il registry per sapere quali server esistono realmente
    from src.mcp_manager import mcp_manager

    mcp_manager.load_registry()
    registry_slugs = set(mcp_manager._registry.keys())

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

    # Batch-fetch preferences and credential hints for all enabled slugs
    enabled_slugs = {r.server_slug for r in rows if r.server_slug in registry_slugs}
    pref_map = (
        await get_user_mcp_preference_map(user_id, tenant_id=tenant)
        if not anonymous
        else {}
    )
    hints_map = (
        await batch_list_credentials_hints(user_id, enabled_slugs, tenant_id=tenant)
        if not anonymous and credentials_feature_enabled()
        else {}
    )

    result: List[Dict[str, Any]] = []
    admin_setup_pending: List[Dict[str, str]] = []
    for r in rows:
        # Filtra server rimossi dal registry (eliminati dall'admin in Hub)
        if r.server_slug not in registry_slugs:
            continue
        pub = await integration_row_to_public_dict(
            r,
            user_id=user_id,
            tenant_id=tenant,
            anonymous=anonymous,
            pref_map=pref_map,
            hints_map=hints_map,
        )
        if pub.get("has_oauth") and not pub.get("admin_oauth_configured", True):
            admin_setup_pending.append(
                {
                    "server_slug": r.server_slug,
                    "display_name": str(r.display_name or r.server_slug),
                }
            )
            continue
        pub.pop("admin_oauth_configured", None)
        result.append(pub)

    resp = {
        "integrations": result,
        "credentials_feature_enabled": credentials_feature_enabled(),
        "admin_setup_pending": admin_setup_pending,
    }

    # Store in response cache (skip for anonymous)
    if not anonymous:
        _INTEGRATIONS_CACHE[cache_key] = (time.monotonic(), resp)

    return resp


@router.get("/runtime-errors")
async def list_runtime_mcp_errors(
    profile: str,
    session_id: str = "",
    probe: bool = False,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    """Errori avvio/handshake MCP per i server nel profilo (tool non caricati in chat)."""
    from src.agent_profile import profile_manager
    from src.runtime.mcp_health import (
        get_last_mcp_load_errors,
        probe_profile_mcp_servers,
    )

    user_id = _credential_user_id(auth)
    sid = (session_id or "").strip() or f"health-{user_id}"
    prof = profile_manager.get_profile(profile.strip())
    profile_slugs = {
        s
        for s in (prof.mcp_servers if prof else []) or []
        if s and s != "aion_subagents"
    }

    if probe:
        rows = await probe_profile_mcp_servers(
            profile.strip(),
            user_id=user_id,
            session_id=sid,
        )
    else:
        cached = get_last_mcp_load_errors(sid)
        from src.runtime.mcp_health import _clean_error_message, _hint_for_error
        from src.mcp_manager import mcp_manager

        mcp_manager.load_registry()

        rows = []
        for slug, err in cached.items():
            if slug not in profile_slugs:
                continue
            cfg = mcp_manager.get_server_config(slug) or {}
            hint = _hint_for_error(slug, cfg, err)
            rows.append(
                {
                    "server_slug": slug,
                    "ok": False,
                    "error": _clean_error_message(err),
                    "hint": hint,
                }
            )

    errors = [
        {
            "server_slug": r.get("server_slug"),
            "display_name": r.get("server_slug", "").replace("-", " ").title(),
            "error": r.get("error"),
            "hint": r.get("hint"),
            "reason": "runtime_error",
            "message": r.get("hint") or r.get("error") or "MCP non disponibile",
        }
        for r in rows
        if not r.get("ok")
    ]
    return {"errors": errors, "has_errors": bool(errors), "probes": rows}


@router.get("/pending")
async def list_pending_integrations(
    profile: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    user_id = _credential_user_id(auth)
    tenant = _tenant_id()
    anonymous = auth.via == "anonymous" or not (auth.identifier or auth.user_row_id)
    pending = await list_pending_for_profile(
        profile,
        user_id,
        tenant_id=tenant,
        anonymous=anonymous,
    )
    return {
        "pending": pending,
        "credentials_feature_enabled": credentials_feature_enabled(),
    }


class PreferenceBody(BaseModel):
    is_active: bool


@router.patch("/{server_slug}/preference")
async def patch_integration_preference(
    server_slug: str,
    body: PreferenceBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    _require_identity_for_mutation(auth)
    user_id = _credential_user_id(auth)
    tenant = _tenant_id()

    async with get_async_session_maker()() as session:
        cfg = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == server_slug,
                    )
                )
            )
            .scalars()
            .first()
        )
    if cfg:
        if not cfg.is_enabled_for_users and body.is_active:
            raise HTTPException(status_code=404, detail="Integration not enabled")
        if not getattr(cfg, "user_may_disable", True) and not body.is_active:
            raise HTTPException(
                status_code=403, detail="This integration cannot be disabled by users"
            )
    else:
        # If it doesn't exist in the database configuration, we only allow disabling it
        if body.is_active:
            raise HTTPException(
                status_code=404, detail="Integration not found or not configured"
            )

    await set_user_mcp_preference(
        user_id, server_slug, body.is_active, tenant_id=tenant
    )
    clear_integrations_cache()
    return {"ok": True, "server_slug": server_slug, "is_active": body.is_active}


class CredentialSetBody(BaseModel):
    server_slug: str
    credentials: Dict[str, str] = Field(default_factory=dict)
    display_hints: Optional[Dict[str, str]] = None


@router.post("/credentials")
async def save_credentials(
    body: CredentialSetBody,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    _require_credentials_enabled()
    _require_identity_for_mutation(auth)
    user_id = _credential_user_id(auth)
    tenant = _tenant_id()

    async with get_async_session_maker()() as session:
        cfg = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == body.server_slug,
                        McpServerConfig.is_enabled_for_users.is_(True),
                    )
                )
            )
            .scalars()
            .first()
        )
    if not cfg:
        raise HTTPException(
            status_code=404, detail="Integration not found or not enabled"
        )

    for key, value in body.credentials.items():
        hint = (body.display_hints or {}).get(key)
        await set_credential(
            user_id,
            body.server_slug,
            key,
            value,
            tenant_id=tenant,
            display_hint=hint,
        )

    from src.runtime.mcp_credential_invalidate import invalidate_mcp_credentials_runtime

    await invalidate_mcp_credentials_runtime(
        user_id, body.server_slug, tenant_id=tenant
    )

    clear_integrations_cache()
    return {
        "ok": True,
        "server_slug": body.server_slug,
        "saved_keys": list(body.credentials.keys()),
    }


@router.delete("/credentials/{server_slug}/{credential_key}")
async def delete_user_credential(
    server_slug: str,
    credential_key: str,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    _require_credentials_enabled()
    _require_identity_for_mutation(auth)
    user_id = _credential_user_id(auth)
    tenant = _tenant_id()
    deleted = await delete_credential(
        user_id, server_slug, credential_key, tenant_id=tenant
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Credential not found")
    from src.runtime.mcp_credential_invalidate import invalidate_mcp_credentials_runtime

    await invalidate_mcp_credentials_runtime(user_id, server_slug, tenant_id=tenant)
    clear_integrations_cache()
    return {"ok": True}


import json
import logging
from datetime import datetime, timezone
import httpx

logger = logging.getLogger("aion.api.mcp_integrations")


def _oauth_dynamic_registration_enabled() -> bool:
    return os.getenv("AION_MCP_OAUTH_DYNAMIC_REGISTRATION", "1").lower() in (
        "1",
        "true",
        "yes",
    )


def _is_absolute_http_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _public_api_base_url() -> str:
    """Absolute public API base (scheme + host + optional path prefix). Skips relative `/api`."""
    for key in (
        "AION_OAUTH_REDIRECT_BASE_URL",
        "AION_PUBLIC_API_URL",
        "AION_FASTAPI_URL",
    ):
        val = (os.getenv(key) or "").strip().rstrip("/")
        if _is_absolute_http_url(val):
            return val
    return ""


def _oauth_redirect_api_base(request: Optional[Request] = None) -> str:
    """
    Browser-facing API base for OAuth callbacks (…/api), not the internal uvicorn URL.

    ``AION_PUBLIC_API_URL=http://localhost:8001`` is valid for server-side fetch but
    wrong for OAuth — prefer Caddy ``Host`` + ``/api`` or ``AION_OAUTH_REDIRECT_BASE_URL``.
    """
    explicit = (os.getenv("AION_OAUTH_REDIRECT_BASE_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(explicit):
        return explicit

    public = (os.getenv("AION_PUBLIC_API_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(public):
        if public.lower().endswith("/api"):
            return public
        # https://dominio.example.com → https://dominio.example.com/api
        return f"{public}/api"

    chat = (os.getenv("AION_CHAT_URL") or "").strip().rstrip("/")
    if _is_absolute_http_url(chat):
        return f"{chat}/api"

    if request is not None:
        fwd_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
        host = fwd_host or request.headers.get("host", "").split(",")[0].strip()
        scheme = fwd_proto or request.url.scheme
        prefix = (request.headers.get("x-forwarded-prefix") or "/api").strip() or "/api"
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        if host:
            return f"{scheme}://{host}{prefix.rstrip('/')}"

    domain = (os.getenv("DOMAIN") or "").strip()
    if domain and domain not in (":80", "http://:80"):
        host = domain.lstrip("http://").lstrip("https://").strip("/")
        if host and not host.startswith(":"):
            scheme = (
                "https" if (os.getenv("LETS_ENCRYPT_EMAIL") or "").strip() else "http"
            )
            return f"{scheme}://{host}/api"

    caddy_port = (os.getenv("CADDY_HTTP_PORT") or "80").strip() or "80"
    return f"http://localhost:{caddy_port}/api"


def _default_oauth_redirect_uri() -> str:
    base = _oauth_redirect_api_base()
    return f"{base.rstrip('/')}/v1/integrations/oauth/callback"


def _resolve_oauth_redirect_uri(
    redirect_uri: Optional[str],
    request: Optional[Request] = None,
) -> str:
    """
    OAuth providers require an absolute redirect_uri.

    chat-ui in Docker uses NEXT_PUBLIC_AION_API_URL=/api (relative, same-origin fetch).
    Resolve to https://host/api/v1/integrations/oauth/callback via env or proxy headers.
    """
    raw = (redirect_uri or "").strip() or _default_oauth_redirect_uri()
    if _is_absolute_http_url(raw):
        return raw

    if raw.startswith("/"):
        base = _oauth_redirect_api_base(request)
        if raw.startswith("/api/"):
            # /api/v1/... behind Caddy → {base}/v1/... when base already ends with /api
            suffix = raw[4:]  # "/v1/integrations/oauth/callback"
            return f"{base.rstrip('/')}{suffix}"
        return f"{base.rstrip('/')}{raw}"

    raise HTTPException(
        status_code=400,
        detail=(
            "OAuth redirect_uri deve essere un URL assoluto "
            "(es. https://dominio.example.com/api/v1/integrations/oauth/callback). "
            "In Docker imposta AION_OAUTH_REDIRECT_BASE_URL=https://<dominio>/api "
            f"(o AION_PUBLIC_API_URL che termini con /api). Ricevuto: {raw!r}"
        ),
    )


def _apply_catalog_oauth_defaults(
    oauth_cfg: Dict[str, Any], server_slug: str, reg_cfg: Dict[str, Any]
) -> Dict[str, Any]:
    from src.mcp_connector_catalog import (
        load_mcp_connector_catalog,
        merge_oauth_config,
        oauth_config_from_connector,
        resolve_connector_row_for_mcp_server,
        resolve_oauth_url_templates,
    )

    catalog = load_mcp_connector_catalog()
    row = resolve_connector_row_for_mcp_server(server_slug, reg_cfg, catalog)
    merged = merge_oauth_config(
        oauth_cfg,
        oauth_config_from_connector(row),
        catalog_overrides=True,
    )
    remote_url = str(reg_cfg.get("remote_url") or merged.get("remote_url") or "")
    return resolve_oauth_url_templates(merged, remote_url=remote_url)


def _oauth_scope_param(oauth_cfg: Dict[str, Any]) -> str:
    scope = oauth_cfg.get("scope")
    if scope:
        return str(scope)
    scopes = oauth_cfg.get("scopes")
    if isinstance(scopes, list):
        return " ".join(str(s) for s in scopes if s)
    return ""


async def _oauth_dynamic_client_register(
    *,
    server_slug: str,
    oauth_cfg: Dict[str, Any],
    redirect_uri: str,
    request: Optional[Request] = None,
) -> bool:
    """RFC 7591 dynamic registration. Returns True if client_id was obtained."""
    import asyncio

    if not _oauth_dynamic_registration_enabled():
        return False
    if (oauth_cfg.get("client_id") or "").strip():
        return False

    if not _is_absolute_http_url(redirect_uri):
        redirect_uri = _resolve_oauth_redirect_uri(redirect_uri, request)

    reg_endpoint = (oauth_cfg.get("registration_endpoint") or "").strip()
    if not reg_endpoint:
        auth_server = (oauth_cfg.get("authorization_server") or "").strip()
        if auth_server:
            from src.mcp_credential_discovery import fetch_authorization_server_metadata

            as_meta = await asyncio.to_thread(
                fetch_authorization_server_metadata, auth_server
            )
            reg_endpoint = str(
                (as_meta or {}).get("registration_endpoint") or ""
            ).strip()
            if reg_endpoint:
                oauth_cfg["registration_endpoint"] = reg_endpoint

    if not reg_endpoint:
        return False

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as hclient:
            reg_payload = {
                "client_name": "AION Agent",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
            reg_resp = await hclient.post(
                reg_endpoint,
                json=reg_payload,
                headers={"Content-Type": "application/json"},
            )
            if reg_resp.status_code not in (200, 201):
                logger.warning(
                    "oauth_start: dynamic registration HTTP %s slug=%s redirect_uri=%r body=%s",
                    reg_resp.status_code,
                    server_slug,
                    redirect_uri,
                    reg_resp.text[:300],
                )
                return False
            reg_data = reg_resp.json()
            new_client_id = str(reg_data.get("client_id") or "").strip()
            if not new_client_id:
                return False
            oauth_cfg["client_id"] = new_client_id
            oauth_cfg["client_id_source"] = "dynamic_registration"
            if reg_data.get("client_secret"):
                oauth_cfg["client_secret"] = reg_data["client_secret"]
            from src.runtime.mcp_oauth_audit import log_dynamic_client_registration

            log_dynamic_client_registration(
                server_slug=server_slug,
                registration_endpoint=reg_endpoint,
                client_id=new_client_id,
            )
            logger.info(
                "oauth_start: dynamic client registration OK slug=%s client_id=%s",
                server_slug,
                new_client_id,
            )
            return True
    except Exception as reg_exc:
        logger.warning(
            "oauth_start: dynamic client registration failed slug=%s: %s",
            server_slug,
            reg_exc,
        )
    return False


async def _resolve_oauth_config_for_server(
    server_slug: str, oauth_cfg: Dict[str, Any]
) -> Dict[str, Any]:
    from src.mcp_manager import mcp_manager

    reg_cfg = mcp_manager.get_server_config(server_slug) or {}
    oauth_cfg = _apply_catalog_oauth_defaults(oauth_cfg, server_slug, reg_cfg)
    if oauth_cfg.get("token_url") and oauth_cfg.get("authorization_server"):
        return oauth_cfg
    try:
        from src.mcp_credential_discovery import discover_mcp_credentials

        discovered = discover_mcp_credentials(server_slug, reg_cfg)
        if discovered and discovered.remote_auth_type == "oauth2":
            oauth_cfg = dict(oauth_cfg)
            oauth_cfg["provider"] = (
                oauth_cfg.get("provider")
                or discovered.remote_oauth_provider
                or "generic"
            )
            oauth_cfg["authorization_server"] = (
                oauth_cfg.get("authorization_server") or discovered.remote_oauth_server
            )
            oauth_cfg["token_url"] = (
                oauth_cfg.get("token_url") or discovered.remote_oauth_token_url
            )
    except Exception:
        pass
    return oauth_cfg


class OAuthCallbackBody(BaseModel):
    server_slug: str
    code: str
    state: str
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None


@router.post("/oauth/callback")
async def oauth_callback(
    body: OAuthCallbackBody,
    request: Request,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    _require_credentials_enabled()
    _require_identity_for_mutation(auth)

    async with get_async_session_maker()() as session:
        cfg = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == body.server_slug
                    )
                )
            )
            .scalars()
            .first()
        )

    if not cfg:
        raise HTTPException(
            status_code=400, detail=f"Server '{body.server_slug}' not found."
        )

    try:
        oauth_cfg = json.loads(cfg.oauth_config_json) if cfg.oauth_config_json else {}
    except Exception:
        oauth_cfg = {}

    oauth_cfg = await _resolve_oauth_config_for_server(body.server_slug, oauth_cfg)

    token_url = oauth_cfg.get("token_url")
    if not token_url:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth token_url is not configured or discovered for server '{body.server_slug}'.",
        )

    redirect_uri = _resolve_oauth_redirect_uri(body.redirect_uri, request)

    from src.runtime.oauth_token_exchange import (
        OAuthTokenExchangeError,
        exchange_authorization_code,
    )

    try:
        token_data = await exchange_authorization_code(
            token_url,
            code=body.code,
            redirect_uri=redirect_uri,
            code_verifier=body.code_verifier,
            client_id=oauth_cfg.get("client_id"),
            client_secret=oauth_cfg.get("client_secret"),
            resource=oauth_cfg.get("resource"),
        )
    except OAuthTokenExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user_id = _credential_user_id(auth)
    tenant = _tenant_id()

    await persist_oauth_token_response(
        user_id,
        body.server_slug,
        token_data,
        oauth_cfg,
        tenant_id=tenant,
    )

    clear_integrations_cache()
    return {"ok": True, "server_slug": body.server_slug}


# --- OAuth PKCE and Status Endpoints ---
import secrets
import hashlib
import base64

_oauth_pending: dict[
    str, dict
] = {}  # state -> {server_slug, code_verifier, user_id, expires_at}


def _cleanup_expired_states() -> None:
    now = datetime.now(timezone.utc)
    expired = [
        state
        for state, data in list(_oauth_pending.items())
        if data["expires_at"] < now
    ]
    for state in expired:
        _oauth_pending.pop(state, None)


def _generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(96)  # 128 chars
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


@router.get("/oauth/start")
async def oauth_start(
    request: Request,
    server_slug: str,
    redirect_uri: Optional[str] = None,
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> Dict[str, Any]:
    """
    Avvia il flow OAuth 2.0 PKCE per un server MCP remoto.

    Implementa la spec MCP OAuth completa:
    1. Discovery del resource server via /.well-known/oauth-protected-resource
    2. Discovery dell'authorization server via /.well-known/oauth-authorization-server
    3. Dynamic Client Registration (RFC 7591) se non abbiamo già un client_id
    4. Build dell'authorization URL con PKCE
    """
    _require_credentials_enabled()
    _require_identity_for_mutation(auth)
    _cleanup_expired_states()

    user_id = _credential_user_id(auth)

    async with get_async_session_maker()() as session:
        cfg = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == server_slug
                    )
                )
            )
            .scalars()
            .first()
        )

    if not cfg:
        raise HTTPException(
            status_code=400, detail=f"Server '{server_slug}' not found."
        )

    try:
        oauth_cfg = json.loads(cfg.oauth_config_json) if cfg.oauth_config_json else {}
    except Exception:
        oauth_cfg = {}

    from src.mcp_manager import mcp_manager as _mgr

    _mgr.load_registry()
    reg_cfg = _mgr.get_server_config(server_slug) or {}
    oauth_cfg = _apply_catalog_oauth_defaults(oauth_cfg, server_slug, reg_cfg)

    # Determina il redirect_uri prima della discovery (serve per la dynamic registration)
    raw_redirect_uri = redirect_uri
    redirect_uri = _resolve_oauth_redirect_uri(redirect_uri, request)
    logger.info(
        "oauth_start: slug=%s redirect_uri raw=%r resolved=%r oauth_base_env=%r",
        server_slug,
        raw_redirect_uri,
        redirect_uri,
        (os.getenv("AION_OAUTH_REDIRECT_BASE_URL") or "").strip() or None,
    )

    modified = False

    # ─── STEP 1: Discovery dal resource server ───────────────────────────────
    # Se non abbiamo ancora l'authorization server, prova la discovery completa
    if (
        not oauth_cfg.get("authorization_server")
        or not oauth_cfg.get("token_url")
        or not oauth_cfg.get("authorization_endpoint")
    ):
        remote_url = reg_cfg.get("remote_url") or oauth_cfg.get("remote_url") or ""

        if remote_url:
            try:
                import asyncio

                from src.mcp_credential_discovery import (
                    _fetch_protected_resource_metadata,
                    fetch_authorization_server_metadata,
                )

                resource_meta = await asyncio.to_thread(
                    _fetch_protected_resource_metadata, remote_url
                )
                auth_servers = resource_meta.get("authorization_servers", [])

                if resource_meta.get("resource") and not oauth_cfg.get("resource"):
                    oauth_cfg["resource"] = resource_meta["resource"]
                    modified = True

                if auth_servers:
                    auth_server_url = auth_servers[0]
                    if not oauth_cfg.get("authorization_server"):
                        oauth_cfg["authorization_server"] = auth_server_url
                        modified = True

                    as_meta = await asyncio.to_thread(
                        fetch_authorization_server_metadata, auth_server_url
                    )
                    if as_meta:
                        if not oauth_cfg.get("token_url") and as_meta.get(
                            "token_endpoint"
                        ):
                            oauth_cfg["token_url"] = as_meta["token_endpoint"]
                            modified = True
                        if not oauth_cfg.get("authorization_endpoint") and as_meta.get(
                            "authorization_endpoint"
                        ):
                            oauth_cfg["authorization_endpoint"] = as_meta[
                                "authorization_endpoint"
                            ]
                            modified = True
                        if not oauth_cfg.get("registration_endpoint") and as_meta.get(
                            "registration_endpoint"
                        ):
                            oauth_cfg["registration_endpoint"] = as_meta[
                                "registration_endpoint"
                            ]
                            modified = True

                    if await _oauth_dynamic_client_register(
                        server_slug=server_slug,
                        oauth_cfg=oauth_cfg,
                        redirect_uri=redirect_uri,
                        request=request,
                    ):
                        modified = True

            except Exception as disc_exc:
                logger.warning(
                    "oauth_start: discovery failed for slug=%s: %s",
                    server_slug,
                    disc_exc,
                )

    # Endpoints già in DB ma client_id mancante (es. prima registrazione fallita).
    if await _oauth_dynamic_client_register(
        server_slug=server_slug,
        oauth_cfg=oauth_cfg,
        redirect_uri=redirect_uri,
        request=request,
    ):
        modified = True

    # Dopo discovery, riapplica catalogo (corregge endpoint errati su host MCP remoto)
    oauth_cfg = _apply_catalog_oauth_defaults(oauth_cfg, server_slug, reg_cfg)

    # ─── Salva le info aggiornate nel DB ─────────────────────────────────────
    if modified:
        async with get_async_session_maker()() as session:
            db_cfg = (
                (
                    await session.execute(
                        select(McpServerConfig).where(
                            McpServerConfig.server_slug == server_slug
                        )
                    )
                )
                .scalars()
                .first()
            )
            if db_cfg:
                db_cfg.oauth_config_json = json.dumps(oauth_cfg)
                await session.commit()

    # ─── Verifica che abbiamo il necessario ──────────────────────────────────
    auth_server = oauth_cfg.get("authorization_server")
    authorization_endpoint = oauth_cfg.get("authorization_endpoint")
    if not auth_server:
        raise HTTPException(
            status_code=400,
            detail=(
                "OAuth non configurato per questo server: impossibile scoprire l'authorization server. "
                "Contatta l'amministratore o verifica che il server supporti lo standard MCP OAuth "
                "o che il catalogo connettori definisca il blocco oauth: (es. Google Workspace MCP)."
            ),
        )

    client_id = (oauth_cfg.get("client_id") or "").strip()
    needs_client_id = bool(oauth_cfg.get("client_credentials_required")) or (
        "login.microsoftonline.com" in str(authorization_endpoint or "").lower()
    )
    if not client_id and needs_client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "OAuth client ID non configurato. L'amministratore deve registrare un'app "
                "in Microsoft Entra ID (o Google/GitHub Cloud) e inserire client ID e secret "
                "in Admin → MCP Hub per questo connettore, con redirect URI: "
                f"{redirect_uri}"
            ),
        )
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "OAuth client_id non disponibile per questo connettore. "
                "Verifica AION_MCP_OAUTH_DYNAMIC_REGISTRATION=1, la connettività verso il "
                f"provider (es. mcp.clickup.com) e che il redirect URI sia corretto: {redirect_uri}"
            ),
        )

    # Fallback per l'authorization_endpoint se non trovato nella discovery
    if not authorization_endpoint:
        authorization_endpoint = f"{auth_server.rstrip('/')}/authorize"

    # ─── Build PKCE + state ───────────────────────────────────────────────────
    code_verifier, code_challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    from datetime import timedelta

    _oauth_pending[state] = {
        "server_slug": server_slug,
        "code_verifier": code_verifier,
        "user_id": user_id,
        "redirect_uri": redirect_uri,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
    }

    import urllib.parse

    params: Dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    scope = _oauth_scope_param(oauth_cfg)
    if scope:
        params["scope"] = scope

    resource = oauth_cfg.get("resource")
    if resource:
        params["resource"] = str(resource)

    authorize_params = oauth_cfg.get("authorize_params")
    if isinstance(authorize_params, dict):
        for key, val in authorize_params.items():
            if val is not None and str(val).strip():
                params[str(key)] = str(val)

    authorization_url = f"{authorization_endpoint}?{urllib.parse.urlencode(params)}"
    logger.info(
        "oauth_start: slug=%s auth_endpoint=%s client_id=%s redirect=%s",
        server_slug,
        authorization_endpoint,
        client_id or "(none)",
        redirect_uri,
    )
    return {"authorization_url": authorization_url, "state": state}


@router.get("/oauth/callback")
async def oauth_callback_redirect(code: str, state: str, request: Request):
    _require_credentials_enabled()
    _cleanup_expired_states()

    pending = _oauth_pending.pop(state, None)
    chat_base = _chat_base_url(request)

    if not pending:
        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error=Sessione+OAuth+scaduta+o+non+valida"
        )

    server_slug = pending["server_slug"]
    code_verifier = pending["code_verifier"]
    user_id = pending["user_id"]
    tenant = _tenant_id()

    async with get_async_session_maker()() as session:
        cfg = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug == server_slug
                    )
                )
            )
            .scalars()
            .first()
        )

    if not cfg:
        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error=Server+non+trovato"
        )

    try:
        oauth_cfg = json.loads(cfg.oauth_config_json) if cfg.oauth_config_json else {}
    except Exception:
        oauth_cfg = {}

    oauth_cfg = await _resolve_oauth_config_for_server(server_slug, oauth_cfg)

    token_url = oauth_cfg.get("token_url")
    if not token_url:
        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error=Token+URL+non+configurato"
        )

    callback_redirect_uri = _resolve_oauth_redirect_uri(
        pending.get("redirect_uri"), request
    )

    from src.runtime.oauth_token_exchange import (
        OAuthTokenExchangeError,
        exchange_authorization_code,
    )

    try:
        token_data = await exchange_authorization_code(
            token_url,
            code=code,
            redirect_uri=callback_redirect_uri,
            code_verifier=code_verifier,
            client_id=oauth_cfg.get("client_id"),
            client_secret=oauth_cfg.get("client_secret"),
            resource=oauth_cfg.get("resource"),
        )
    except OAuthTokenExchangeError as exc:
        import urllib.parse

        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error={urllib.parse.quote_plus(str(exc))}"
        )

    await persist_oauth_token_response(
        user_id,
        server_slug,
        token_data,
        oauth_cfg,
        tenant_id=tenant,
    )

    return RedirectResponse(
        url=f"{chat_base}/integrations?oauth_status=success&server_slug={server_slug}"
    )


@router.get("/{server_slug}/oauth-status")
async def oauth_status(
    server_slug: str, auth: ChatAuthIdentity = Depends(require_chat_auth)
) -> Dict[str, Any]:
    _require_credentials_enabled()
    user_id = _credential_user_id(auth)
    tenant = _tenant_id()

    from src.runtime.credential_store import get_credential

    token = await get_credential(user_id, server_slug, "OAUTH_TOKEN", tenant_id=tenant)
    return {"connected": token is not None, "server_slug": server_slug}
