"""Integrity checks and cleanup for MCP integrations (registry, DB policy, user credentials)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import delete, func, select

from src.data.engine import get_async_session_maker
from src.data.models import McpServerConfig, UserMcpCredential, UserMcpPreference
from src.mcp_connector_catalog import (
    infer_connector_id_for_registry_name,
    load_mcp_connector_catalog,
)
from src.mcp_integration_sync import (
    _AION_USER_RE,
    _slug_env_prefix,
    validate_policy_vs_registry,
)

IssueSeverity = str  # "error" | "warning" | "info"


def enrich_credential_schema_with_env_placeholders(
    schema: List[Dict[str, Any]],
    server_slug: str,
    *,
    credential_mode: str = "per_user",
) -> List[Dict[str, Any]]:
    """Aggiunge ``env_placeholder`` e ``registry_env_key`` per copy/paste YAML."""
    if not schema:
        return []
    prefix = _slug_env_prefix(server_slug)
    out: List[Dict[str, Any]] = []
    for raw in schema:
        field = dict(raw)
        key = str(field.get("key") or "").strip()
        if not key:
            out.append(field)
            continue
        if credential_mode == "per_user":
            field["env_placeholder"] = f"${{AION_USER_{prefix}__{key}}}"
        elif credential_mode == "org_shared":
            field["env_placeholder"] = f"${{{key}}}"
        else:
            field.pop("env_placeholder", None)
        field["registry_env_key"] = key
        out.append(field)
    return out


def build_suggested_env_yaml_block(
    server_slug: str,
    schema: List[Dict[str, Any]],
    *,
    credential_mode: str = "per_user",
) -> str:
    """Snippet YAML ``env:`` pronto per il registry."""
    enriched = enrich_credential_schema_with_env_placeholders(
        schema, server_slug, credential_mode=credential_mode
    )
    if not enriched:
        return "env: {}"
    lines = ["env:"]
    for field in enriched:
        env_key = str(field.get("registry_env_key") or field.get("key") or "").strip()
        placeholder = field.get("env_placeholder")
        if env_key and placeholder:
            lines.append(f'  {env_key}: "{placeholder}"')
    return "\n".join(lines)


async def delete_mcp_user_data(server_slug: str) -> Dict[str, int]:
    """Rimuove credenziali e preferenze utente per uno slug MCP."""
    async with get_async_session_maker()() as session:
        cred_res = await session.execute(
            delete(UserMcpCredential).where(
                UserMcpCredential.server_slug == server_slug
            )
        )
        pref_res = await session.execute(
            delete(UserMcpPreference).where(
                UserMcpPreference.server_slug == server_slug
            )
        )
        await session.commit()
    return {
        "credentials_deleted": int(cred_res.rowcount or 0),
        "preferences_deleted": int(pref_res.rowcount or 0),
    }


def _credential_ts(row: UserMcpCredential) -> datetime:
    ts = row.updated_at or row.created_at
    if ts is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


async def migrate_credentials_to_slug(
    old_slug: str,
    new_slug: str,
    *,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Sposta credenziali/preferenze da uno slug orfano al nuovo slug installato.

    In caso di chiave già presente su ``new_slug`` (stesso user/tenant/key),
    conserva la riga più recente ed elimina il duplicato.
    """
    empty = {"migrated": 0, "merged": 0, "deleted_duplicates": 0, "total": 0}
    if not old_slug or not new_slug or old_slug == new_slug:
        return empty
    async with get_async_session_maker()() as session:
        old_rows = (
            (
                await session.execute(
                    select(UserMcpCredential).where(
                        UserMcpCredential.server_slug == old_slug
                    )
                )
            )
            .scalars()
            .all()
        )
        if not old_rows:
            return empty
        if dry_run:
            return {**empty, "migrated": len(old_rows), "total": len(old_rows)}

        migrated = merged = deleted = 0
        for row in old_rows:
            existing = (
                (
                    await session.execute(
                        select(UserMcpCredential).where(
                            UserMcpCredential.user_id == row.user_id,
                            UserMcpCredential.tenant_id == row.tenant_id,
                            UserMcpCredential.server_slug == new_slug,
                            UserMcpCredential.credential_key == row.credential_key,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing is None:
                row.server_slug = new_slug
                migrated += 1
                continue
            if _credential_ts(row) > _credential_ts(existing):
                existing.value_encrypted = row.value_encrypted
                existing.display_hint = row.display_hint or existing.display_hint
                existing.expires_at = row.expires_at or existing.expires_at
                await session.delete(row)
                merged += 1
            else:
                await session.delete(row)
                deleted += 1

        old_prefs = (
            (
                await session.execute(
                    select(UserMcpPreference).where(
                        UserMcpPreference.server_slug == old_slug
                    )
                )
            )
            .scalars()
            .all()
        )
        for pref in old_prefs:
            existing_pref = (
                (
                    await session.execute(
                        select(UserMcpPreference).where(
                            UserMcpPreference.user_id == pref.user_id,
                            UserMcpPreference.tenant_id == pref.tenant_id,
                            UserMcpPreference.server_slug == new_slug,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing_pref is None:
                pref.server_slug = new_slug
            else:
                existing_pref.is_active = bool(
                    existing_pref.is_active or pref.is_active
                )
                await session.delete(pref)

        await session.commit()
    total = migrated + merged + deleted
    return {
        "migrated": migrated,
        "merged": merged,
        "deleted_duplicates": deleted,
        "total": total,
    }


def _connector_id_for_slug(
    slug: str,
    *,
    registry: Dict[str, Any],
    policy_by_slug: Dict[str, McpServerConfig],
    catalog: Dict[str, Any],
) -> Optional[str]:
    cfg = registry.get(slug) or {}
    explicit = str(cfg.get("aion_connector_id") or "").strip()
    if explicit:
        return explicit
    row = policy_by_slug.get(slug)
    if row and getattr(row, "aion_connector_id", None):
        return str(row.aion_connector_id).strip() or None
    inferred = infer_connector_id_for_registry_name(slug, catalog)
    return inferred or None


async def find_migratable_credential_slugs(
    new_slug: str,
    connector_id: Optional[str],
    *,
    registry_slugs: Set[str],
) -> List[str]:
    """Trova slug orfani con credenziali migrabili verso ``new_slug``."""
    if not connector_id:
        return []
    catalog = load_mcp_connector_catalog()
    async with get_async_session_maker()() as session:
        cred_slugs = (
            (await session.execute(select(UserMcpCredential.server_slug).distinct()))
            .scalars()
            .all()
        )
        policies = (await session.execute(select(McpServerConfig))).scalars().all()
    policy_by_slug = {p.server_slug: p for p in policies}
    from src.mcp_manager import mcp_manager

    mcp_manager.load_registry()
    registry = mcp_manager._registry

    candidates: List[str] = []
    for old_slug in cred_slugs:
        if old_slug == new_slug or old_slug in registry_slugs:
            continue
        old_connector = _connector_id_for_slug(
            old_slug,
            registry=registry,
            policy_by_slug=policy_by_slug,
            catalog=catalog,
        )
        if old_connector == connector_id:
            candidates.append(old_slug)
    return candidates


async def auto_migrate_credentials_for_connector(
    new_slug: str,
    connector_id: Optional[str],
    *,
    registry_slugs: Set[str],
) -> Dict[str, Any]:
    """Migra credenziali da slug orfani con lo stesso ``aion_connector_id``."""
    migrated: List[Dict[str, Any]] = []
    for old_slug in await find_migratable_credential_slugs(
        new_slug, connector_id, registry_slugs=registry_slugs
    ):
        result = await migrate_credentials_to_slug(old_slug, new_slug)
        if result.get("total"):
            migrated.append({"from_slug": old_slug, **result})
    return {
        "migrated": migrated,
        "total": sum(m.get("total", 0) for m in migrated),
    }


async def scan_mcp_integrity() -> Dict[str, Any]:
    """Analizza registry, policy DB e credenziali utente."""
    from src.mcp_manager import mcp_manager

    mcp_manager.load_registry()
    registry_slugs = set(mcp_manager.get_all_servers())
    registry = mcp_manager._registry
    catalog = load_mcp_connector_catalog()

    issues: List[Dict[str, Any]] = []

    async with get_async_session_maker()() as session:
        policies = (await session.execute(select(McpServerConfig))).scalars().all()
        cred_slug_rows = (
            await session.execute(
                select(
                    UserMcpCredential.server_slug,
                    func.count().label("n"),
                ).group_by(UserMcpCredential.server_slug)
            )
        ).all()
        pref_slug_rows = (
            await session.execute(
                select(
                    UserMcpPreference.server_slug,
                    func.count().label("n"),
                ).group_by(UserMcpPreference.server_slug)
            )
        ).all()

    policy_by_slug = {p.server_slug: p for p in policies}
    configured_slugs = set(policy_by_slug)

    for slug, count in cred_slug_rows:
        if slug not in registry_slugs:
            issues.append(
                {
                    "code": "orphan_credentials",
                    "severity": "warning",
                    "server_slug": slug,
                    "count": int(count),
                    "message": (
                        f"Credenziali utente ({count}) per '{slug}' senza MCP nel registry"
                    ),
                    "repair": "purge_credentials",
                }
            )

    for slug, count in pref_slug_rows:
        if slug not in registry_slugs:
            issues.append(
                {
                    "code": "orphan_preferences",
                    "severity": "info",
                    "server_slug": slug,
                    "count": int(count),
                    "message": f"Preferenze utente ({count}) per '{slug}' orfane",
                    "repair": "purge_preferences",
                }
            )

    for slug in configured_slugs - registry_slugs:
        issues.append(
            {
                "code": "stale_policy",
                "severity": "warning",
                "server_slug": slug,
                "message": f"Policy DB per '{slug}' senza voce nel registry",
                "repair": "delete_policy",
            }
        )

    for slug in registry_slugs - configured_slugs:
        if slug in mcp_manager._registry_base:
            continue
        issues.append(
            {
                "code": "unconfigured_registry",
                "severity": "info",
                "server_slug": slug,
                "message": f"MCP '{slug}' nel registry senza policy in DB",
                "repair": "sync_from_registry",
            }
        )

    for slug in registry_slugs:
        cfg = registry.get(slug) or {}
        policy = policy_by_slug.get(slug)
        if not policy:
            continue
        mode = getattr(policy, "credential_mode", None) or "none"
        schema = json.loads(policy.credential_schema_json or "[]")
        warnings = validate_policy_vs_registry(
            slug, cfg, mode, credential_schema=schema
        )
        for w in warnings:
            issues.append(
                {
                    "code": "policy_env_mismatch",
                    "severity": "error",
                    "server_slug": slug,
                    "message": w,
                    "repair": "apply_suggested_env",
                }
            )

        if mode == "per_user":
            env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
            prefix = _slug_env_prefix(slug)
            for field in schema:
                key = str(field.get("key") or "").strip()
                if not key:
                    continue
                expected = f"${{AION_USER_{prefix}__{key}}}"
                env_val = str(env.get(key) or "").strip()
                if env_val and env_val != expected and not _AION_USER_RE.match(env_val):
                    issues.append(
                        {
                            "code": "env_literal_secret",
                            "severity": "warning",
                            "server_slug": slug,
                            "field_key": key,
                            "message": (
                                f"Env '{key}' usa valore letterale invece del placeholder "
                                f"per-utente {expected}"
                            ),
                            "repair": "apply_suggested_env",
                            "expected_placeholder": expected,
                        }
                    )
                elif mode == "per_user" and key in env and not env_val:
                    issues.append(
                        {
                            "code": "env_empty_placeholder",
                            "severity": "info",
                            "server_slug": slug,
                            "field_key": key,
                            "message": f"Env '{key}' vuoto nel registry",
                            "repair": "apply_suggested_env",
                        }
                    )

    # Credenziali migrabili (stesso connector, slug diverso)
    for slug in registry_slugs:
        policy = policy_by_slug.get(slug)
        connector_id = None
        if policy and getattr(policy, "aion_connector_id", None):
            connector_id = str(policy.aion_connector_id)
        if not connector_id:
            connector_id = _connector_id_for_slug(
                slug,
                registry=registry,
                policy_by_slug=policy_by_slug,
                catalog=catalog,
            )
        if not connector_id:
            continue
        migratable = await find_migratable_credential_slugs(
            slug, connector_id, registry_slugs=registry_slugs
        )
        for old_slug in migratable:
            issues.append(
                {
                    "code": "migratable_credentials",
                    "severity": "warning",
                    "server_slug": slug,
                    "from_slug": old_slug,
                    "connector_id": connector_id,
                    "message": (
                        f"Credenziali da '{old_slug}' migrabili verso '{slug}' "
                        f"(stesso connettore {connector_id})"
                    ),
                    "repair": "migrate_credentials",
                }
            )

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    issues.sort(
        key=lambda i: (severity_rank.get(i["severity"], 9), i.get("server_slug", ""))
    )

    return {
        "ok": not any(i["severity"] == "error" for i in issues),
        "issue_count": len(issues),
        "issues": issues,
        "summary": {
            "registry_count": len(registry_slugs),
            "policy_count": len(configured_slugs),
            "credential_slugs": len(cred_slug_rows),
        },
    }


async def _credential_mode_for_slug(server_slug: str) -> str:
    async with get_async_session_maker()() as session:
        row = (
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
    if row and getattr(row, "credential_mode", None):
        return str(row.credential_mode)
    return "per_user"


async def repair_mcp_integrity_issue(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Esegue una singola azione di riparazione suggerita dall'integrità."""
    repair = issue.get("repair")
    slug = str(issue.get("server_slug") or "")
    if repair == "purge_credentials" and slug:
        async with get_async_session_maker()() as session:
            res = await session.execute(
                delete(UserMcpCredential).where(UserMcpCredential.server_slug == slug)
            )
            await session.commit()
        return {"ok": True, "deleted": int(res.rowcount or 0)}
    if repair == "purge_preferences" and slug:
        async with get_async_session_maker()() as session:
            res = await session.execute(
                delete(UserMcpPreference).where(UserMcpPreference.server_slug == slug)
            )
            await session.commit()
        return {"ok": True, "deleted": int(res.rowcount or 0)}
    if repair == "delete_policy" and slug:
        async with get_async_session_maker()() as session:
            await session.execute(
                delete(McpServerConfig).where(McpServerConfig.server_slug == slug)
            )
            await session.commit()
        return {"ok": True}
    if repair == "sync_from_registry" and slug:
        from src.mcp_integration_sync import sync_mcp_server_config_from_registry

        row = await sync_mcp_server_config_from_registry(slug)
        return {"ok": bool(row)}
    if repair == "apply_suggested_env" and slug:
        from src.mcp_integration_sync import apply_integration_config

        mode = await _credential_mode_for_slug(slug)
        if mode not in ("per_user", "org_shared"):
            mode = "per_user"
        result = await apply_integration_config(
            slug,
            credential_mode=mode,
            apply_suggested_env=True,
            force_replace_schema_env=True,
            sync_db=False,
        )
        return result if isinstance(result, dict) else {"ok": False}
    if repair == "migrate_credentials":
        old_slug = str(issue.get("from_slug") or "")
        if old_slug and slug:
            result = await migrate_credentials_to_slug(old_slug, slug)
            return {"ok": True, **result}
    return {"ok": False, "error": "unknown repair action"}
