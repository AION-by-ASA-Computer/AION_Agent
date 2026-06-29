"""Shared logic for user MCP integrations, pending credentials, preferences."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select

from src.agent_profile import profile_manager
from src.data.engine import get_async_session_maker
from src.data.ids import new_uuid7_str
from src.data.models import McpServerConfig, UserMcpCredential, UserMcpPreference
from src.runtime.credential_store import (
    list_credentials_hints,
    user_credentials_enabled,
)


def credentials_feature_enabled() -> bool:
    return user_credentials_enabled()


async def get_user_mcp_preference_map(
    user_id: str,
    *,
    tenant_id: str = "default",
) -> Dict[str, bool]:
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(UserMcpPreference).where(
                        UserMcpPreference.user_id == user_id,
                        UserMcpPreference.tenant_id == tenant_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    return {r.server_slug: r.is_active for r in rows}


async def batch_list_credentials_hints(
    user_id: str,
    server_slugs: Set[str],
    *,
    tenant_id: str = "default",
) -> Dict[str, List[Dict[str, Any]]]:
    """Batch-fetch all credential hints for the given slugs in a single query."""
    if not server_slugs:
        return {}
    now = datetime.now(timezone.utc)
    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.user_id == user_id,
                        UserMcpCredential.tenant_id == tenant_id,
                        UserMcpCredential.server_slug.in_(server_slugs),
                    )
                )
            )
            .scalars()
            .all()
        )
    result: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        slug = r.server_slug
        if slug not in result:
            result[slug] = []
        is_expired = False
        if r.expires_at:
            exp = r.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            is_expired = exp < now
        result[slug].append(
            {
                "key": r.credential_key,
                "display_hint": r.display_hint,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "is_expired": is_expired,
            }
        )
    return result


async def set_user_mcp_preference(
    user_id: str,
    server_slug: str,
    is_active: bool,
    *,
    tenant_id: str = "default",
) -> None:
    async with get_async_session_maker()() as session:
        row = (
            (
                await session.execute(
                    select(UserMcpPreference).where(
                        UserMcpPreference.user_id == user_id,
                        UserMcpPreference.tenant_id == tenant_id,
                        UserMcpPreference.server_slug == server_slug,
                    )
                )
            )
            .scalars()
            .first()
        )
        if row:
            row.is_active = is_active
        else:
            session.add(
                UserMcpPreference(
                    id=new_uuid7_str(),
                    user_id=user_id,
                    tenant_id=tenant_id,
                    server_slug=server_slug,
                    is_active=is_active,
                )
            )
        await session.commit()


def user_mcp_effective_active(
    server_slug: str,
    *,
    pref_map: Dict[str, bool],
    user_may_disable: bool,
) -> bool:
    if not user_may_disable:
        return True
    if server_slug in pref_map:
        return pref_map[server_slug]
    return True


async def integration_row_to_public_dict(
    r: McpServerConfig,
    *,
    user_id: str,
    tenant_id: str,
    anonymous: bool,
    pref_map: Optional[Dict[str, bool]] = None,
    hints_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    if pref_map is None:
        pref_map = (
            await get_user_mcp_preference_map(user_id, tenant_id=tenant_id)
            if not anonymous
            else {}
        )

    schema = json.loads(r.credential_schema_json or "[]")
    try:
        from src.mcp_credential_discovery import (
            discover_mcp_credentials,
            merge_schema_sources,
        )
        from src.mcp_manager import mcp_manager

        mcp_manager.load_registry()
        reg_cfg = mcp_manager.get_server_config(r.server_slug) or {}
        reg_env = reg_cfg.get("env") if isinstance(reg_cfg.get("env"), dict) else {}
        if reg_env:
            discovered = discover_mcp_credentials(r.server_slug, reg_cfg)
            allowed = {k.strip() for k in reg_env if isinstance(k, str) and k.strip()}
            from_registry = [f for f in discovered.schema if f.get("key") in allowed]
            if from_registry:
                schema = merge_schema_sources(
                    catalog_schema=schema,
                    discovered_schema=from_registry,
                )
    except Exception:
        pass
    schema = [
        s for s in schema if s.get("key") and not str(s["key"]).startswith("AION_USER_")
    ]
    oauth_cfg = json.loads(r.oauth_config_json or "{}")
    if not oauth_cfg.get("authorization_server") and not oauth_cfg.get("auth_url"):
        try:
            from src.mcp_credential_discovery import discover_mcp_credentials
            from src.mcp_manager import mcp_manager

            reg_cfg = mcp_manager.get_server_config(r.server_slug) or {}
            discovered = discover_mcp_credentials(r.server_slug, reg_cfg)
            if discovered and discovered.remote_auth_type == "oauth2":
                oauth_cfg = {
                    "provider": discovered.remote_oauth_provider or "generic",
                    "authorization_server": discovered.remote_oauth_server,
                    "token_url": discovered.remote_oauth_token_url,
                    "scopes": [],
                }
        except Exception:
            pass

    mode = getattr(r, "credential_mode", None) or "none"
    if mode == "none" and r.requires_user_credentials:
        mode = "per_user"
    show_form = mode == "per_user" and r.requires_user_credentials
    org_managed = mode == "org_shared"
    user_may_disable = bool(getattr(r, "user_may_disable", True))
    user_enabled = user_mcp_effective_active(
        r.server_slug, pref_map=pref_map, user_may_disable=user_may_disable
    )

    hints: List[Dict[str, Any]] = []
    if show_form and credentials_feature_enabled() and not anonymous and user_enabled:
        if hints_map is not None:
            hints = hints_map.get(r.server_slug, [])
        else:
            hints = await list_credentials_hints(
                user_id, r.server_slug, tenant_id=tenant_id
            )

    # Include saved credential keys not in admin schema so users can still edit them.
    if show_form and hints:
        schema_keys = {str(s.get("key")) for s in schema if s.get("key")}
        for h in hints:
            hk = str(h.get("key") or "").strip()
            if not hk or hk in schema_keys:
                continue
            schema.append(
                {
                    "key": hk,
                    "label": h.get("display_hint") or hk,
                    "type": "password",
                    "required": False,
                    "description": "Campo salvato in precedenza (opzionale)",
                }
            )
            schema_keys.add(hk)

    from src.runtime.credential_store import credential_key_aliases

    required_fields = [s for s in schema if s.get("required") and s.get("key")]
    req_keys = {s["key"] for s in required_fields}
    hint_keys_expanded: set[str] = set()
    for h in hints:
        hk = str(h.get("key") or "").strip()
        if not hk:
            continue
        hint_keys_expanded.add(hk)
        hint_keys_expanded.update(credential_key_aliases(hk))
    configured = (
        (not r.requires_user_credentials)
        or (not req_keys)
        or all(
            any(alias in hint_keys_expanded for alias in credential_key_aliases(rk))
            for rk in req_keys
        )
    )

    try:
        from src.mcp_manager import mcp_manager as _mm

        _mm.load_registry()
        _reg = _mm.get_server_config(r.server_slug) or {}
        _is_remote_bridge = _reg.get("type") == "remote-bridge"
    except Exception:
        _is_remote_bridge = False

    remote_auth_type = None
    if _is_remote_bridge:
        try:
            from src.mcp_credential_discovery import discover_mcp_credentials

            discovered = discover_mcp_credentials(r.server_slug, _reg)
            remote_auth_type = discovered.remote_auth_type
        except Exception:
            pass

    has_oauth = bool(
        oauth_cfg.get("authorization_server")
        or oauth_cfg.get("auth_url")
        or (remote_auth_type == "oauth2")
    )

    return {
        "server_slug": r.server_slug,
        "display_name": r.display_name,
        "description": r.description,
        "icon_url": r.icon_url,
        "category": r.category,
        "credential_mode": mode,
        "requires_user_credentials": r.requires_user_credentials,
        "credential_schema": schema if show_form else [],
        "has_oauth": has_oauth,
        "is_remote_bridge": _is_remote_bridge,
        "remote_url": oauth_cfg.get("remote_url") or "",
        "oauth_provider": oauth_cfg.get("provider"),
        "oauth_authorization_server": oauth_cfg.get("authorization_server")
        or oauth_cfg.get("auth_url"),
        "oauth_client_id": oauth_cfg.get("client_id"),
        "oauth_scopes": oauth_cfg.get("scopes") or [],
        "is_configured": configured if show_form else (org_managed or mode == "none"),
        "org_managed": org_managed,
        "user_enabled": user_enabled,
        "can_disable": user_may_disable,
        "credentials_hints": hints if show_form else [],
    }


async def list_pending_for_profile(
    profile_name: str,
    user_id: str,
    *,
    tenant_id: str = "default",
    anonymous: bool = False,
) -> List[Dict[str, Any]]:
    from src.mcp_manager import mcp_manager

    profile_manager.load_all_if_stale()
    profile = profile_manager.get_profile(profile_name)
    if not profile:
        return []
    mcp_slugs: Set[str] = set(profile.mcp_servers or [])

    # Carica il registry per sapere quali server esistono realmente
    mcp_manager.load_registry()
    registry_slugs: Set[str] = set(mcp_manager._registry.keys())

    async with get_async_session_maker()() as session:
        rows = (
            (
                await session.execute(
                    select(McpServerConfig).where(
                        McpServerConfig.server_slug.in_(mcp_slugs)
                    )
                )
            )
            .scalars()
            .all()
            if mcp_slugs
            else []
        )

    pref_map = (
        await get_user_mcp_preference_map(user_id, tenant_id=tenant_id)
        if not anonymous
        else {}
    )
    pending: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for slug in mcp_slugs:
        # Salta server che non esistono nel registry MCP (es. slug di test nei profili)
        if slug not in registry_slugs:
            continue

        # Salta se l'utente ha disattivato esplicitamente l'integrazione
        if pref_map.get(slug) is False:
            continue

        row = next((r for r in rows if r.server_slug == slug), None)
        if not row:
            # Gli MCP registrati (sia nativi base che locali) sono pronti all'uso
            # e non richiedono configurazione nel DB delle policy per funzionare.
            continue
        if not row.is_enabled_for_users:
            # Gli MCP registrati (sia nativi base che locali) sono sempre abilitati
            # implicitamente per gli utenti, ignorando il flag del DB delle policy.
            continue
        pub = await integration_row_to_public_dict(
            row,
            user_id=user_id,
            tenant_id=tenant_id,
            anonymous=anonymous,
            pref_map=pref_map,
        )
        if not pub["user_enabled"]:
            continue
        mode = pub["credential_mode"]
        if (
            mode == "per_user"
            and pub["requires_user_credentials"]
            and not pub["is_configured"]
        ):
            missing = [
                s["key"]
                for s in json.loads(row.credential_schema_json or "[]")
                if s.get("required")
            ]
            pending.append(
                {
                    "server_slug": slug,
                    "display_name": row.display_name,
                    "reason": "credentials_missing",
                    "missing_keys": missing,
                    "message": "Configure your personal credentials to use this tool.",
                    "integration": pub,
                }
            )
        seen.add(slug)

    return pending
