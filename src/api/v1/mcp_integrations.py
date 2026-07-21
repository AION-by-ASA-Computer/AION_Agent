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


def _chat_base_url() -> str:
    """URL base del chat-ui per redirect OAuth utente."""
    return (os.getenv("AION_CHAT_URL") or "http://localhost:8003").rstrip("/")


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
    for r in rows:
        # Filtra server rimossi dal registry (eliminati dall'admin in Hub)
        if r.server_slug not in registry_slugs:
            continue
        result.append(
            await integration_row_to_public_dict(
                r,
                user_id=user_id,
                tenant_id=tenant,
                anonymous=anonymous,
                pref_map=pref_map,
                hints_map=hints_map,
            )
        )

    resp = {
        "integrations": result,
        "credentials_feature_enabled": credentials_feature_enabled(),
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

    await invalidate_mcp_credentials_runtime(
        user_id, server_slug, tenant_id=tenant
    )
    clear_integrations_cache()
    return {"ok": True}


import json
import logging
from datetime import datetime, timezone
import httpx

logger = logging.getLogger("aion.api.mcp_integrations")


class OAuthCallbackBody(BaseModel):
    server_slug: str
    code: str
    state: str
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None


@router.post("/oauth/callback")
async def oauth_callback(
    body: OAuthCallbackBody,
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

    if not oauth_cfg.get("token_url"):
        try:
            from src.mcp_credential_discovery import discover_mcp_credentials
            from src.mcp_manager import mcp_manager

            reg_cfg = mcp_manager.get_server_config(body.server_slug) or {}
            discovered = discover_mcp_credentials(body.server_slug, reg_cfg)
            if discovered and discovered.remote_auth_type == "oauth2":
                oauth_cfg["provider"] = (
                    oauth_cfg.get("provider")
                    or discovered.remote_oauth_provider
                    or "generic"
                )
                oauth_cfg["authorization_server"] = (
                    oauth_cfg.get("authorization_server")
                    or discovered.remote_oauth_server
                )
                oauth_cfg["token_url"] = (
                    oauth_cfg.get("token_url") or discovered.remote_oauth_token_url
                )
        except Exception:
            pass

    token_url = oauth_cfg.get("token_url")
    if not token_url:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth token_url is not configured or discovered for server '{body.server_slug}'.",
        )

    client_id = oauth_cfg.get("client_id")
    client_secret = oauth_cfg.get("client_secret")

    payload = {
        "grant_type": "authorization_code",
        "code": body.code,
    }
    if body.code_verifier:
        payload["code_verifier"] = body.code_verifier
    if client_id:
        payload["client_id"] = client_id
    if client_secret:
        payload["client_secret"] = client_secret

    if body.redirect_uri:
        payload["redirect_uri"] = body.redirect_uri
    else:
        aion_api_base = (
            os.getenv("AION_OAUTH_REDIRECT_BASE_URL")
            or os.getenv("AION_FASTAPI_URL")
            or "http://localhost:8001"
        )
        payload["redirect_uri"] = (
            f"{aion_api_base.rstrip('/')}/v1/integrations/oauth/callback"
        )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data=payload, headers=headers)
            resp.raise_for_status()
            token_data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "OAuth token exchange failed with status %d: %s",
            e.response.status_code,
            e.response.text,
        )
        raise HTTPException(
            status_code=400, detail=f"OAuth provider error: {e.response.text}"
        )
    except Exception as e:
        logger.exception("OAuth token exchange error")
        raise HTTPException(
            status_code=502, detail=f"Failed to connect to OAuth provider: {str(e)}"
        )

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=400,
            detail=f"No access_token returned by OAuth provider: {token_data}",
        )

    user_id = _credential_user_id(auth)
    tenant = _tenant_id()

    expires_in = token_data.get("expires_in")
    expires_at = None
    if expires_in is not None:
        try:
            from datetime import timedelta

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except Exception:
            pass

    await set_credential(
        user_id,
        body.server_slug,
        "OAUTH_TOKEN",
        access_token,
        tenant_id=tenant,
        display_hint=oauth_cfg.get("provider", "oauth2"),
        expires_at=expires_at,
    )

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        await set_credential(
            user_id,
            body.server_slug,
            "OAUTH_REFRESH_TOKEN",
            refresh_token,
            tenant_id=tenant,
        )

    from src.runtime.mcp_credential_invalidate import invalidate_mcp_credentials_runtime

    await invalidate_mcp_credentials_runtime(
        user_id, body.server_slug, tenant_id=tenant
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

    # Determina il redirect_uri prima della discovery (serve per la dynamic registration)
    if not redirect_uri:
        aion_api_base = (
            os.getenv("AION_OAUTH_REDIRECT_BASE_URL")
            or os.getenv("AION_FASTAPI_URL")
            or "http://localhost:8001"
        )
        redirect_uri = f"{aion_api_base.rstrip('/')}/v1/integrations/oauth/callback"

    modified = False

    # ─── STEP 1: Discovery dal resource server ───────────────────────────────
    # Se non abbiamo ancora l'authorization server, prova la discovery completa
    if (
        not oauth_cfg.get("authorization_server")
        or not oauth_cfg.get("token_url")
        or not oauth_cfg.get("authorization_endpoint")
    ):
        from src.mcp_manager import mcp_manager as _mgr

        _mgr.load_registry()
        reg_cfg = _mgr.get_server_config(server_slug) or {}
        remote_url = reg_cfg.get("remote_url") or oauth_cfg.get("remote_url") or ""

        if remote_url:
            try:
                async with httpx.AsyncClient(
                    timeout=8.0, follow_redirects=True
                ) as hclient:
                    # RFC 9728: /.well-known/oauth-protected-resource
                    resource_meta = {}

                    from urllib.parse import urlparse, urlunparse

                    parsed_url = urlparse(remote_url)

                    # Prova prima a livello di host root (consigliato RFC) e poi sotto il subpath
                    urls_to_try = []
                    if parsed_url.netloc:
                        urls_to_try.append(
                            urlunparse(
                                (
                                    parsed_url.scheme,
                                    parsed_url.netloc,
                                    "/.well-known/oauth-protected-resource",
                                    "",
                                    "",
                                    "",
                                )
                            )
                        )
                    urls_to_try.append(
                        f"{remote_url.rstrip('/')}/.well-known/oauth-protected-resource"
                    )

                    for well_known_url in urls_to_try:
                        try:
                            r = await hclient.get(well_known_url)
                            if r.status_code == 200:
                                resource_meta = r.json()
                                break
                        except Exception:
                            continue

                    auth_servers = resource_meta.get("authorization_servers", [])
                    # Fallback: se l'MCP server restituisce il link in WWW-Authenticate o nel body JSON (es. ClickUp)
                    if not auth_servers:
                        try:
                            r401 = await hclient.get(remote_url)
                            rm_url = None

                            # 1. Prova a estrarre dal WWW-Authenticate header
                            www_auth = r401.headers.get("www-authenticate", "")
                            import re

                            m = re.search(r'resource_metadata="([^"]+)"', www_auth)
                            if m:
                                rm_url = m.group(1)
                            else:
                                # 2. Prova a estrarre dal body JSON
                                try:
                                    body_json = r401.json()
                                    if (
                                        isinstance(body_json, dict)
                                        and "resource_metadata" in body_json
                                    ):
                                        rm_url = body_json["resource_metadata"]
                                except Exception:
                                    pass

                            if rm_url:
                                rmr = await hclient.get(rm_url)
                                if rmr.status_code == 200:
                                    resource_meta = rmr.json()
                                    auth_servers = resource_meta.get(
                                        "authorization_servers", []
                                    )
                        except Exception:
                            pass

                    if auth_servers:
                        auth_server_url = auth_servers[0]
                        if not oauth_cfg.get("authorization_server"):
                            oauth_cfg["authorization_server"] = auth_server_url
                            modified = True

                        # ─── STEP 2: Discovery dell'authorization server ──────
                        parsed = urlparse(auth_server_url)
                        as_meta = {}
                        metadata_urls = [
                            # RFC 8414: /.well-known/oauth-authorization-server[/{issuer_path}]
                            urlunparse(
                                (
                                    parsed.scheme,
                                    parsed.netloc,
                                    "/.well-known/oauth-authorization-server"
                                    + parsed.path.rstrip("/"),
                                    "",
                                    "",
                                    "",
                                )
                            ),
                            urlunparse(
                                (
                                    parsed.scheme,
                                    parsed.netloc,
                                    "/.well-known/oauth-authorization-server",
                                    "",
                                    "",
                                    "",
                                )
                            ),
                            # OpenID Connect discovery
                            urlunparse(
                                (
                                    parsed.scheme,
                                    parsed.netloc,
                                    "/.well-known/openid-configuration",
                                    "",
                                    "",
                                    "",
                                )
                            ),
                        ]
                        for meta_url in metadata_urls:
                            try:
                                mr = await hclient.get(meta_url)
                                if mr.status_code == 200:
                                    as_meta = mr.json()
                                    break
                            except Exception:
                                continue

                        if as_meta:
                            if not oauth_cfg.get("token_url") and as_meta.get(
                                "token_endpoint"
                            ):
                                oauth_cfg["token_url"] = as_meta["token_endpoint"]
                                modified = True
                            if not oauth_cfg.get(
                                "authorization_endpoint"
                            ) and as_meta.get("authorization_endpoint"):
                                oauth_cfg["authorization_endpoint"] = as_meta[
                                    "authorization_endpoint"
                                ]
                                modified = True
                            if not oauth_cfg.get(
                                "registration_endpoint"
                            ) and as_meta.get("registration_endpoint"):
                                oauth_cfg["registration_endpoint"] = as_meta[
                                    "registration_endpoint"
                                ]
                                modified = True

                        # ─── STEP 3: Dynamic Client Registration (RFC 7591) ──
                        reg_endpoint = oauth_cfg.get(
                            "registration_endpoint"
                        ) or as_meta.get("registration_endpoint")
                        if reg_endpoint and not oauth_cfg.get("client_id"):
                            try:
                                reg_payload = {
                                    "client_name": "AION Agent",
                                    "redirect_uris": [redirect_uri],
                                    "grant_types": ["authorization_code"],
                                    "response_types": ["code"],
                                    "token_endpoint_auth_method": "none",  # public client (PKCE)
                                }
                                reg_resp = await hclient.post(
                                    reg_endpoint,
                                    json=reg_payload,
                                    headers={"Content-Type": "application/json"},
                                )
                                if reg_resp.status_code in (200, 201):
                                    reg_data = reg_resp.json()
                                    new_client_id = reg_data.get("client_id")
                                    if new_client_id:
                                        oauth_cfg["client_id"] = new_client_id
                                        if reg_data.get("client_secret"):
                                            oauth_cfg["client_secret"] = reg_data[
                                                "client_secret"
                                            ]
                                        modified = True
                                        logger.info(
                                            "oauth_start: dynamic client registration OK slug=%s client_id=%s",
                                            server_slug,
                                            new_client_id,
                                        )
                            except Exception as reg_exc:
                                logger.warning(
                                    "oauth_start: dynamic client registration failed: %s",
                                    reg_exc,
                                )

            except Exception as disc_exc:
                logger.warning(
                    "oauth_start: discovery failed for slug=%s: %s",
                    server_slug,
                    disc_exc,
                )

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
                "Contatta l'amministratore o verifica che il server supporti lo standard MCP OAuth."
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

    client_id = oauth_cfg.get("client_id") or ""

    import urllib.parse

    params: Dict[str, str] = {
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if client_id:
        params["client_id"] = client_id

    scope = oauth_cfg.get("scope")
    if scope:
        params["scope"] = scope

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
    chat_base = _chat_base_url()

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

    if not oauth_cfg.get("token_url"):
        try:
            from src.mcp_credential_discovery import discover_mcp_credentials
            from src.mcp_manager import mcp_manager

            reg_cfg = mcp_manager.get_server_config(server_slug) or {}
            discovered = discover_mcp_credentials(server_slug, reg_cfg)
            if discovered and discovered.remote_auth_type == "oauth2":
                oauth_cfg["provider"] = (
                    oauth_cfg.get("provider")
                    or discovered.remote_oauth_provider
                    or "generic"
                )
                oauth_cfg["authorization_server"] = (
                    oauth_cfg.get("authorization_server")
                    or discovered.remote_oauth_server
                )
                oauth_cfg["token_url"] = (
                    oauth_cfg.get("token_url") or discovered.remote_oauth_token_url
                )
        except Exception:
            pass

    token_url = oauth_cfg.get("token_url")
    if not token_url:
        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error=Token+URL+non+configurato"
        )

    client_id = oauth_cfg.get("client_id")
    client_secret = oauth_cfg.get("client_secret")

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
    }
    if client_id:
        payload["client_id"] = client_id
    if client_secret:
        payload["client_secret"] = client_secret

    # Usa il redirect_uri salvato durante oauth_start per evitare mismatch
    callback_redirect_uri = pending.get("redirect_uri") or (
        f"{(os.getenv('AION_OAUTH_REDIRECT_BASE_URL') or os.getenv('AION_FASTAPI_URL') or 'http://localhost:8001').rstrip('/')}/v1/integrations/oauth/callback"
    )
    payload["redirect_uri"] = callback_redirect_uri

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data=payload, headers=headers)
            resp.raise_for_status()
            token_data = resp.json()
    except Exception as e:
        logger.exception("OAuth token exchange error in GET callback")
        err_msg = str(e)
        if isinstance(e, httpx.HTTPStatusError):
            err_msg = e.response.text
        import urllib.parse

        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error={urllib.parse.quote_plus(err_msg)}"
        )

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse(
            url=f"{chat_base}/integrations?oauth_status=error&error=Nessun+access_token+ricevuto"
        )

    expires_in = token_data.get("expires_in")
    expires_at = None
    if expires_in is not None:
        try:
            from datetime import timedelta

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        except Exception:
            pass

    await set_credential(
        user_id,
        server_slug,
        "OAUTH_TOKEN",
        access_token,
        tenant_id=tenant,
        display_hint=oauth_cfg.get("provider", "oauth2"),
        expires_at=expires_at,
    )

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        await set_credential(
            user_id,
            server_slug,
            "OAUTH_REFRESH_TOKEN",
            refresh_token,
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
