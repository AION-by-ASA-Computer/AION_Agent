"""
Sincronizza McpServerConfig dal registry MCP + catalogo connettori (fonte di verità schema).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from sqlalchemy import select

from .data.engine import get_async_session_maker
from .data.ids import new_uuid7_str
from .data.models import McpServerConfig
from .mcp_connector_catalog import (
    load_mcp_connector_catalog,
    resolve_connector_row_for_mcp_server,
)
from .mcp_credential_discovery import (
    CredentialDiscoveryResult,
    discover_mcp_credentials,
    merge_schema_sources,
)
from .mcp_manager import mcp_manager

CredentialMode = Literal["none", "org_shared", "per_user"]

_AION_USER_RE = re.compile(r"^\$\{AION_USER_")
_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _slug_env_prefix(server_slug: str) -> str:
    return server_slug.upper().replace("-", "_")


def credential_schema_from_connector(
    connector_row: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not connector_row:
        return []
    raw = connector_row.get("credential_fields")
    if isinstance(raw, list) and raw:
        out: List[Dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            if not key:
                continue
            secret = bool(row.get("secret"))
            if "secret" not in row:
                secret = bool(
                    re.search(r"TOKEN|SECRET|PASSWORD|API_KEY|REFRESH", key, re.I)
                )
            ftype = "password" if secret else "text"
            if str(row.get("type") or "").lower() == "oauth":
                ftype = "oauth"
            out.append(
                {
                    "key": key,
                    "label": str(row.get("label") or row.get("label_it") or key),
                    "type": ftype,
                    "required": bool(row.get("required", True)),
                    "description": row.get("description") or row.get("description_it"),
                }
            )
        return out
    req = connector_row.get("required_env") or []
    opt = connector_row.get("optional_env") or []
    schema: List[Dict[str, Any]] = []
    for key in req:
        if isinstance(key, str) and key.strip():
            k = key.strip()
            schema.append(
                {
                    "key": k,
                    "label": k.replace("_", " ").title(),
                    "type": "password"
                    if re.search(r"TOKEN|SECRET|PASSWORD|KEY", k, re.I)
                    else "text",
                    "required": True,
                }
            )
    for key in opt:
        if isinstance(key, str) and key.strip():
            k = key.strip()
            schema.append(
                {
                    "key": k,
                    "label": k.replace("_", " ").title(),
                    "type": "password"
                    if re.search(r"TOKEN|SECRET|PASSWORD|KEY", k, re.I)
                    else "text",
                    "required": False,
                }
            )
    return schema


def suggest_registry_env_for_per_user(
    server_slug: str,
    schema: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Genera env con placeholder ${AION_USER_<SLUG>__<KEY>} per ogni chiave dello schema."""
    prefix = _slug_env_prefix(server_slug)
    out: Dict[str, str] = {}
    for field in schema:
        key = field.get("key")
        if not key:
            continue
        out[str(key)] = f"${{AION_USER_{prefix}__{key}}}"
    return out


def suggest_registry_env_for_org_shared(schema: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for field in schema:
        key = field.get("key")
        if not key:
            continue
        out[str(key)] = f"${{{key}}}"
    return out


def _env_has_literal_secrets(env: Dict[str, Any]) -> bool:
    for v in (env or {}).values():
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        if _AION_USER_RE.match(s):
            continue
        if _ENV_PLACEHOLDER_RE.match(s):
            continue
        return True
    return False


def _env_uses_per_user_placeholders(env: Dict[str, Any]) -> bool:
    for v in (env or {}).values():
        if isinstance(v, str) and _AION_USER_RE.match(v.strip()):
            return True
    return False


def infer_credential_mode(
    server_config: Dict[str, Any],
    connector_row: Optional[Dict[str, Any]],
    discovery: Optional[CredentialDiscoveryResult] = None,
) -> CredentialMode:
    # Gestione speciale per server remote-bridge
    if server_config.get("type") == "remote-bridge":
        env = server_config.get("env")
        if not env or not isinstance(env, dict):
            return "none"
        # "per_user" solo se l'env contiene davvero placeholder di credenziali per-utente
        # (es. ${AION_USER_*}). Un env vuoto o senza placeholder indica auth_type "none".
        if _env_uses_per_user_placeholders(env):
            return "per_user"
        return "none"

    if discovery and discovery.remote_auth_type is not None:
        if discovery.remote_auth_type == "none":
            return "none"
        return "per_user"
    env = server_config.get("env") if isinstance(server_config.get("env"), dict) else {}
    if _env_uses_per_user_placeholders(env):
        return "per_user"
    schema = merge_schema_sources(
        catalog_schema=credential_schema_from_connector(connector_row),
        discovered_schema=(discovery.schema if discovery else []),
    )
    if not schema:
        if discovery and discovery.config_file_auth and not discovery.has_env_auth:
            return "none"
        return "none"
    if _env_has_literal_secrets(env):
        return "org_shared"
    if discovery and discovery.has_env_auth:
        return "per_user"
    if schema and any(
        re.search(
            r"TOKEN|SECRET|PASSWORD|API_KEY|EMAIL|IMAP|SMTP|AUTH",
            str(f.get("key") or ""),
            re.I,
        )
        for f in schema
    ):
        return "per_user"
    cat = (connector_row or {}).get("category") or ""
    if cat in ("productivity", "communication", "project_management"):
        return "per_user"
    return "per_user" if schema else "none"


def validate_policy_vs_registry(
    server_slug: str,
    server_config: Dict[str, Any],
    credential_mode: str,
) -> List[str]:
    warnings: List[str] = []
    env = server_config.get("env") if isinstance(server_config.get("env"), dict) else {}
    if credential_mode == "per_user":
        if _env_has_literal_secrets(env):
            warnings.append(
                "Modalità per_utente ma il registry contiene ancora valori non-placeholder in env. "
                "Rimuovi i segreti globali o applica env suggerito."
            )
        if env and not _env_uses_per_user_placeholders(env):
            warnings.append(
                "Modalità per_utente: applica env suggerito con placeholder ${AION_USER_*}."
            )
    if credential_mode == "org_shared" and _env_uses_per_user_placeholders(env):
        warnings.append(
            "Modalità organizzazione ma env usa ${AION_USER_*}; i token non saranno letti da .env globale."
        )
    return warnings


def _display_meta_from_connector(
    connector_row: Optional[Dict[str, Any]], slug: str
) -> Dict[str, Any]:
    if connector_row:
        return {
            "display_name": str(
                connector_row.get("title") or slug.replace("_", " ").title()
            ),
            "description": connector_row.get("description"),
            "category": connector_row.get("category"),
            "aion_connector_id": str(connector_row.get("id") or ""),
        }
    return {
        "display_name": slug.replace("_", " ").title(),
        "description": None,
        "category": "tools",
        "aion_connector_id": None,
    }


def build_integration_preview(
    server_slug: str,
    *,
    credential_mode: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        mcp_manager.load_registry()
        catalog = load_mcp_connector_catalog()
        cfg = mcp_manager.get_server_config(server_slug) or mcp_manager._registry.get(
            server_slug
        )
    except Exception as e:
        return {"ok": False, "error": f"Errore caricamento registry: {e}"}

    if not cfg:
        return {"ok": False, "error": f"Server '{server_slug}' not in registry"}
    try:
        connector_row = resolve_connector_row_for_mcp_server(server_slug, cfg, catalog)
        discovery = discover_mcp_credentials(server_slug, cfg)
        schema = merge_schema_sources(
            catalog_schema=credential_schema_from_connector(connector_row),
            discovered_schema=discovery.schema,
        )
        mode = credential_mode or infer_credential_mode(cfg, connector_row, discovery)
        if discovery.config_file_auth and not discovery.has_env_auth and mode == "none":
            warnings_list = validate_policy_vs_registry(server_slug, cfg, mode)
            warnings_list.append(
                "Il server sembra usare un file di configurazione locale (es. config.toml / XDG) "
                "senza variabili d'ambiente per le credenziali. Valuta org_shared con volume "
                "sulla home MCP isolata per utente, oppure un server che espone env (MCP_EMAIL_*)."
            )
        else:
            warnings_list = validate_policy_vs_registry(server_slug, cfg, mode)
        if discovery.has_env_auth and not schema:
            warnings_list.append(
                "Discovery ha trovato env ma schema vuoto — verificare installazione."
            )
        if discovery.remote_auth_type == "unreachable":
            warnings_list.append(
                f"Il server remoto non è raggiungibile: {discovery.remote_error or 'timeout o errore di connessione'}"
            )
        suggested_per_user = suggest_registry_env_for_per_user(server_slug, schema)
        suggested_org = suggest_registry_env_for_org_shared(schema)
        return {
            "ok": True,
            "server_slug": server_slug,
            "connector": connector_row,
            "credential_mode": mode,
            "credential_schema": schema,
            "suggested_env_per_user": suggested_per_user,
            "suggested_env_org_shared": suggested_org,
            "current_env": cfg.get("env") or {},
            "warnings": warnings_list,
            "aion_connector_id": (
                cfg.get("aion_connector_id") or (connector_row or {}).get("id")
            ),
            "discovery": {
                "env_keys": discovery.env_keys,
                "sources": discovery.sources,
                "credential_mode_hint": discovery.credential_mode_hint,
                "config_file_auth": discovery.config_file_auth,
                "has_env_auth": discovery.has_env_auth,
                "remote_auth_type": discovery.remote_auth_type,
                "remote_connect_url": discovery.remote_connect_url,
                "remote_docs_url": discovery.remote_docs_url,
                "remote_hint": discovery.remote_hint,
                "remote_error": discovery.remote_error,
                "remote_oauth_provider": discovery.remote_oauth_provider,
                "remote_oauth_server": discovery.remote_oauth_server,
                "remote_oauth_token_url": discovery.remote_oauth_token_url,
            },
        }
    except Exception as e:
        import logging

        logging.getLogger("aion.mcp_integration_sync").exception(
            "build_integration_preview fallita per %s", server_slug
        )
        return {"ok": False, "error": str(e)}


def apply_credential_mode_flags(
    mode: str, requires_user_credentials: Optional[bool] = None
) -> Tuple[str, bool]:
    m = mode if mode in ("none", "org_shared", "per_user") else "none"
    if requires_user_credentials is not None:
        return m, requires_user_credentials
    return m, m == "per_user"


async def sync_mcp_server_config_from_registry(
    server_slug: str,
    *,
    force_schema_from_catalog: bool = True,
    credential_mode: Optional[str] = None,
) -> Optional[McpServerConfig]:
    """Crea o aggiorna McpServerConfig da registry + catalogo."""
    mcp_manager.load_registry()
    if server_slug not in mcp_manager._registry:
        return None
    raw_cfg = mcp_manager._registry.get(server_slug) or {}
    catalog = load_mcp_connector_catalog()
    connector_row = resolve_connector_row_for_mcp_server(server_slug, raw_cfg, catalog)
    discovery = discover_mcp_credentials(server_slug, raw_cfg)
    schema = merge_schema_sources(
        catalog_schema=credential_schema_from_connector(connector_row),
        discovered_schema=discovery.schema,
    )
    mode = credential_mode or infer_credential_mode(raw_cfg, connector_row, discovery)
    meta = _display_meta_from_connector(connector_row, server_slug)
    connector_id = (
        raw_cfg.get("aion_connector_id") or meta.get("aion_connector_id") or ""
    ).strip() or None

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
        now = datetime.now(timezone.utc)
        if row:
            if force_schema_from_catalog and schema:
                current_schema = json.loads(row.credential_schema_json or "[]")
                merged = merge_schema_sources(
                    catalog_schema=current_schema,
                    discovered_schema=schema,
                )
                merged = [
                    s
                    for s in merged
                    if s.get("key") and not str(s["key"]).startswith("AION_USER_")
                ]
                if merged != current_schema:
                    row.credential_schema_json = json.dumps(merged)
            row.credential_mode = mode
            row.requires_user_credentials = mode == "per_user"
            if raw_cfg.get("type") == "remote-bridge":
                try:
                    oauth_cfg = (
                        json.loads(row.oauth_config_json)
                        if row.oauth_config_json
                        else {}
                    )
                except Exception:
                    oauth_cfg = {}
                if not oauth_cfg.get("remote_url"):
                    oauth_cfg["remote_url"] = raw_cfg.get("remote_url", "")
                    oauth_cfg["provider"] = oauth_cfg.get("provider") or "generic"
                    row.oauth_config_json = json.dumps(oauth_cfg)
                # Auto-abilita i server remote-bridge esistenti ancora disabilitati
                if not row.is_enabled_for_users:
                    row.is_enabled_for_users = True
            if connector_id:
                row.aion_connector_id = connector_id
            if meta.get("description") and not row.description:
                row.description = meta["description"]
            if meta.get("category") and not row.category:
                row.category = meta["category"]
            row.updated_at = now
        else:
            oauth_cfg = {}
            if raw_cfg.get("type") == "remote-bridge":
                oauth_cfg["remote_url"] = raw_cfg.get("remote_url", "")
                oauth_cfg["provider"] = "generic"
            # I server remote-bridge vengono abilitati per gli utenti automaticamente
            # perché l'admin li ha installati esplicitamente per la configurazione per-utente
            auto_enabled = raw_cfg.get("type") == "remote-bridge"
            row = McpServerConfig(
                id=new_uuid7_str(),
                server_slug=server_slug,
                display_name=meta["display_name"],
                description=meta.get("description"),
                category=meta.get("category"),
                is_enabled_for_users=auto_enabled,
                requires_user_credentials=mode == "per_user",
                credential_mode=mode,
                aion_connector_id=connector_id,
                credential_schema_json=json.dumps(schema),
                oauth_config_json=json.dumps(oauth_cfg),
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def sync_all_mcp_server_configs_from_registry() -> Dict[str, Any]:
    mcp_manager.load_registry()
    slugs = [
        s for s in mcp_manager.get_all_servers() if s and not str(s).startswith("_")
    ]
    created = updated = skipped = 0
    for slug in slugs:
        existing_before = None
        async with get_async_session_maker()() as session:
            existing_before = (
                (
                    await session.execute(
                        select(McpServerConfig.id).where(
                            McpServerConfig.server_slug == slug
                        )
                    )
                )
                .scalars()
                .first()
            )
        row = await sync_mcp_server_config_from_registry(slug)
        if not row:
            skipped += 1
        elif existing_before:
            updated += 1
        else:
            created += 1
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": len(slugs),
    }


def normalize_env_override(
    env_override: Dict[str, Any],
    credential_mode: str,
    server_slug: str,
) -> Tuple[Dict[str, str], List[str]]:
    """Normalizza env proposto dall'AI (SLUG generico) e valida coerenza con credential_mode."""
    warnings: List[str] = []
    slug_upper = _slug_env_prefix(server_slug)
    out: Dict[str, str] = {}
    for k, v in (env_override or {}).items():
        if not k or v is None:
            continue
        key = str(k).strip()
        val = str(v).strip()
        if "AION_USER_SLUG__" in val:
            val = val.replace("AION_USER_SLUG__", f"AION_USER_{slug_upper}__")
        out[key] = val

    if credential_mode == "per_user":
        for key, val in out.items():
            if not _AION_USER_RE.match(val):
                warnings.append(
                    f"per_user: valore di '{key}' dovrebbe usare placeholder ${{AION_USER_{slug_upper}__{key}}}"
                )
    elif credential_mode == "org_shared":
        for key, val in out.items():
            if _AION_USER_RE.match(val):
                warnings.append(
                    f"org_shared: '{key}' usa ${{AION_USER_*}}; usa ${{{key}}} per env organizzazione."
                )
    return out, warnings


def merge_suggested_env_into_registry(
    server_slug: str,
    credential_mode: str,
    *,
    preserve_existing_keys: bool = True,
    credential_schema: Optional[List[Dict[str, Any]]] = None,
    env_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Applica env suggerito al registry locale (non committa segreti)."""
    preview = build_integration_preview(server_slug, credential_mode=credential_mode)
    if not preview.get("ok"):
        return preview
    schema = (
        credential_schema
        if credential_schema is not None
        else (preview.get("credential_schema") or [])
    )
    if env_override:
        suggested, norm_warnings = normalize_env_override(
            env_override, credential_mode, server_slug
        )
        preview_warnings = list(preview.get("warnings") or [])
        preview_warnings.extend(norm_warnings)
    elif credential_mode == "per_user":
        suggested = suggest_registry_env_for_per_user(server_slug, schema)
        preview_warnings = preview.get("warnings") or []
    elif credential_mode == "org_shared":
        suggested = suggest_registry_env_for_org_shared(schema)
        preview_warnings = preview.get("warnings") or []
    else:
        suggested = {}
        preview_warnings = preview.get("warnings") or []
    cfg = mcp_manager.get_server_config(server_slug) or {}
    env = dict(cfg.get("env") or {})
    if preserve_existing_keys:
        for k, v in suggested.items():
            if k not in env or not str(env.get(k) or "").strip():
                env[k] = v
    else:
        env.update(suggested)
    mcp_manager.update_server_config(server_slug, {"env": env})
    cfg_after = mcp_manager.get_server_config(server_slug) or {}
    cfg_after = {**cfg_after, "env": env}
    policy_warnings = validate_policy_vs_registry(
        server_slug, cfg_after, credential_mode
    )
    all_warnings = list(preview_warnings) + policy_warnings
    return {
        "ok": True,
        "env": env,
        "server_slug": server_slug,
        "warnings": all_warnings,
    }


async def apply_integration_config(
    server_slug: str,
    *,
    credential_mode: str,
    credential_schema: Optional[List[Dict[str, Any]]] = None,
    env_override: Optional[Dict[str, Any]] = None,
    apply_suggested_env: bool = False,
    schema_override: bool = False,
    registry_patch: Optional[Dict[str, Any]] = None,
    is_enabled_for_users: Optional[bool] = None,
    requires_user_credentials: Optional[bool] = None,
    user_may_disable: Optional[bool] = None,
    display_name: Optional[str] = None,
    oauth_config: Optional[Dict[str, Any]] = None,
    sync_db: bool = True,
) -> Dict[str, Any]:
    """
    Pipeline unico: patch registry, env suggerito, sync mcp_server_configs.
    Usato da wizard commit, apply-suggested-env e post-install normalize.
    """
    mcp_manager.load_registry()
    if server_slug not in mcp_manager._registry:
        return {"ok": False, "error": f"Server '{server_slug}' not in registry"}

    mode, req_creds = apply_credential_mode_flags(
        credential_mode,
        requires_user_credentials,
    )

    allowed_registry = {
        "command",
        "args",
        "env",
        "description",
        "security",
        "aion_connector_id",
    }
    if registry_patch:
        update_data = {k: v for k, v in registry_patch.items() if k in allowed_registry}
        if update_data:
            mcp_manager.update_server_config(server_slug, update_data)

    env_result: Dict[str, Any] = {"ok": True}
    if apply_suggested_env and mode in ("per_user", "org_shared"):
        env_result = merge_suggested_env_into_registry(
            server_slug,
            mode,
            credential_schema=credential_schema if schema_override else None,
            env_override=env_override,
        )
        if not env_result.get("ok"):
            return env_result

    # Cleanup per "none": rimuovi env e auth headers dai remote MCP
    if mode == "none":
        cfg = mcp_manager.get_server_config(server_slug) or {}
        is_remote = (
            cfg.get("type") == "remote-bridge"
            or cfg.get("aion_market_install") == "remote"
        )

        updates: Dict[str, Any] = {}

        # 1) Rimuovi env (impostare a {})
        if cfg.get("env"):
            updates["env"] = {}

        # 2) Se remote-bridge, rimuovi --header dagli args
        if is_remote:
            args = list(cfg.get("args") or [])
            cleaned_args: List[str] = []
            skip_next = False
            for arg in args:
                if skip_next:
                    skip_next = False
                    continue
                if arg == "--header":
                    # Rimuovi tutti gli header (contengono auth per remote MCP "none")
                    skip_next = True
                    continue
                cleaned_args.append(arg)
            if cleaned_args != args:
                updates["args"] = cleaned_args

        if updates:
            mcp_manager.update_server_config(server_slug, updates)

    if sync_db:
        await sync_mcp_server_config_from_registry(
            server_slug,
            force_schema_from_catalog=not schema_override,
            credential_mode=mode,
        )
        async with get_async_session_maker()() as session:
            db_row = (
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
            if db_row:
                db_row.credential_mode = mode
                db_row.requires_user_credentials = req_creds
                if schema_override and credential_schema is not None:
                    db_row.credential_schema_json = json.dumps(credential_schema)
                if is_enabled_for_users is not None:
                    db_row.is_enabled_for_users = is_enabled_for_users
                if user_may_disable is not None:
                    db_row.user_may_disable = user_may_disable
                if display_name:
                    db_row.display_name = display_name
                if oauth_config is not None:
                    db_row.oauth_config_json = json.dumps(oauth_config)
                db_row.updated_at = datetime.now(timezone.utc)
                await session.commit()

    out: Dict[str, Any] = {
        "ok": True,
        "server_slug": server_slug,
        "credential_mode": mode,
        "requires_user_credentials": req_creds,
    }
    if env_result.get("env") is not None:
        out["env"] = env_result["env"]
    if env_result.get("warnings"):
        out["warnings"] = env_result["warnings"]
    return out
