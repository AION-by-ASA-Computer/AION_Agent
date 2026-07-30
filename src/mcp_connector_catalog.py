"""Load curated MCP connector catalog (YAML) for admin UI."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("aion.mcp_connector_catalog")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def connector_catalog_path() -> Path:
    """Catalogo opzionale (override tenant). La discovery automatica non dipende da questo file."""
    return _repo_root() / "config" / "mcp_connector_catalog.yaml"


def connector_catalog_std_path() -> Path:
    """Template committato in config_std/ (source of truth)."""
    return _repo_root() / "config_std" / "mcp_connector_catalog.yaml"


def resolve_connector_catalog_path() -> Path | None:
    """Preferisce config/ locale; fallback su config_std/ se assente."""
    local = connector_catalog_path()
    if local.exists():
        return local
    std = connector_catalog_std_path()
    if std.exists():
        return std
    return None


def infer_connector_id_for_registry_name(
    registry_name: str, catalog: Dict[str, Any]
) -> str | None:
    """
    Associa un nome server MCP nel registry (es. ``clickup-mcp-server``) a un ``id`` del catalogo connettori,
    usando ``mcp_name_hints`` se presenti, altrimenti l'id del connettore come hint debole.
    Preferisce il hint più lungo che compare nel nome (meno ambiguo).
    """
    n = (registry_name or "").lower().replace("_", "-")
    winner: str | None = None
    win_len = 0
    for c in catalog.get("connectors") or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not cid:
            continue
        cid_s = str(cid)
        hints_raw = c.get("mcp_name_hints")
        if isinstance(hints_raw, list) and hints_raw:
            hints = [str(h).lower().replace("_", "-") for h in hints_raw if h]
        else:
            hints = [cid_s.lower().replace("_", "-")]
        for h in hints:
            if len(h) < 3:
                continue
            if h in n:
                if len(h) > win_len:
                    win_len = len(h)
                    winner = cid_s
    return winner


def valid_connector_ids(catalog: Dict[str, Any]) -> set[str]:
    return {
        str(c["id"])
        for c in (catalog.get("connectors") or [])
        if isinstance(c, dict) and c.get("id")
    }


def _connector_by_id(
    catalog: Dict[str, Any], connector_id: str
) -> Dict[str, Any] | None:
    want = (connector_id or "").strip().lower()
    if not want:
        return None
    for c in catalog.get("connectors") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip().lower()
        if cid == want:
            return c
    return None


def resolve_connector_row_for_mcp_server(
    registry_server_name: str,
    server_config: Dict[str, Any],
    catalog: Dict[str, Any],
) -> Dict[str, Any] | None:
    """
    Riga catalogo associata a un server MCP nel registry: ``aion_connector_id`` se presente,
    altrimenti inferenza da ``mcp_name_hints`` / id (come Hub e infer_connector_id_for_registry_name).
    """
    explicit = (server_config.get("aion_connector_id") or "").strip()
    if explicit:
        row = _connector_by_id(catalog, explicit)
        if row:
            return row
    inferred = infer_connector_id_for_registry_name(registry_server_name, catalog)
    if inferred:
        return _connector_by_id(catalog, inferred)
    return None


def connector_auth_type(connector: Dict[str, Any] | None) -> str:
    if not connector:
        return ""
    return str(connector.get("auth_type") or "").strip().lower()


def connector_requires_oauth(connector: Dict[str, Any] | None) -> bool:
    """True se il connettore dichiara ``auth_type: oauth2`` nel catalogo YAML."""
    return connector_auth_type(connector) == "oauth2"


def oauth_ui_metadata_from_connector(
    connector: Dict[str, Any] | None,
    *,
    fallback_provider: str = "",
    fallback_display_name: str = "",
) -> Dict[str, str]:
    """
    Metadati OAuth per API/UI — fonte primaria: catalogo YAML (``title``, ``oauth_provider``, ``auth_type``).
    """
    if connector and connector_requires_oauth(connector):
        provider = str(
            connector.get("oauth_provider") or connector.get("id") or ""
        ).strip()
        display = str(connector.get("title") or connector.get("id") or "").strip()
    else:
        provider = (fallback_provider or "").strip()
        display = (fallback_display_name or fallback_provider or "").strip()
    if not display:
        display = provider or "OAuth"
    if not provider:
        provider = "generic"
    return {"provider": provider, "oauth_display_name": display}


def oauth_config_from_connector(connector: Dict[str, Any] | None) -> Dict[str, Any]:
    """
    Endpoint OAuth statici dal blocco ``oauth:`` del catalogo YAML.

    Usato per connettori che non espongono MCP OAuth discovery (es. Google Workspace MCP).
    """
    if not connector:
        return {}
    raw = connector.get("oauth")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in (
        "authorization_server",
        "authorization_endpoint",
        "token_url",
        "registration_endpoint",
        "client_id",
        "client_secret",
        "resource",
    ):
        val = raw.get(key)
        if val is not None and str(val).strip():
            out[key] = str(val).strip()
    scopes = raw.get("scopes")
    if isinstance(scopes, list):
        out["scopes"] = [str(s).strip() for s in scopes if s and str(s).strip()]
    elif isinstance(scopes, str) and scopes.strip():
        out["scopes"] = [scopes.strip()]
    if raw.get("client_credentials_required"):
        out["client_credentials_required"] = True
    authorize_params = raw.get("authorize_params")
    if isinstance(authorize_params, dict) and authorize_params:
        out["authorize_params"] = {
            str(k): str(v) for k, v in authorize_params.items() if k and v is not None
        }
    return out


def oauth_admin_client_credentials_required(oauth_cfg: Dict[str, Any] | None) -> bool:
    """True se l'admin deve registrare client_id/secret (es. GitHub, SharePoint, Gmail)."""
    cfg = oauth_cfg or {}
    if cfg.get("client_credentials_required"):
        return True
    auth_ref = str(
        cfg.get("authorization_endpoint") or cfg.get("authorization_server") or ""
    ).lower()
    return "login.microsoftonline.com" in auth_ref


def oauth_admin_credentials_configured(oauth_cfg: Dict[str, Any] | None) -> bool:
    """False se mancano client_id o client_secret richiesti dall'admin."""
    if not oauth_admin_client_credentials_required(oauth_cfg):
        return True
    cfg = oauth_cfg or {}
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    return bool(client_id and client_secret)


_ENTRA_TENANT_IN_REMOTE_URL = re.compile(
    r"/tenants/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def extract_entra_tenant_id_from_remote_url(remote_url: str) -> str | None:
    """Estrae il GUID tenant Entra da URL Agent 365 (…/tenants/{id}/servers/…)."""
    match = _ENTRA_TENANT_IN_REMOTE_URL.search(remote_url or "")
    return match.group(1) if match else None


def resolve_oauth_url_templates(
    oauth_cfg: Dict[str, Any], *, remote_url: str = ""
) -> Dict[str, Any]:
    """Sostituisce ``{tenant_id}`` negli endpoint OAuth usando l'URL MCP installato."""
    tenant_id = extract_entra_tenant_id_from_remote_url(remote_url)
    if not tenant_id:
        return oauth_cfg
    out = dict(oauth_cfg)
    for key in (
        "authorization_server",
        "authorization_endpoint",
        "token_url",
        "resource",
    ):
        val = out.get(key)
        if isinstance(val, str) and "{tenant_id}" in val:
            out[key] = val.replace("{tenant_id}", tenant_id)
    return out


_CATALOG_OAUTH_OVERRIDE_KEYS = frozenset(
    {
        "authorization_server",
        "authorization_endpoint",
        "token_url",
        "registration_endpoint",
        "scopes",
        "authorize_params",
        "client_credentials_required",
        "resource",
    }
)
_ADMIN_OAUTH_KEYS = frozenset({"client_id", "client_secret"})


def merge_oauth_config(
    base: Dict[str, Any],
    defaults: Dict[str, Any],
    *,
    catalog_overrides: bool = False,
) -> Dict[str, Any]:
    """
    Unisce ``defaults`` in ``base``.

    Con ``catalog_overrides=True`` (catalogo YAML), gli endpoint OAuth del catalogo
    sostituiscono valori errati già in DB (es. discovery su host MCP remoto).
    ``client_id`` / ``client_secret`` configurati dall'admin non vengono mai sovrascritti.
    """
    if not defaults:
        return base
    merged = dict(base)
    for key, val in defaults.items():
        if key in _ADMIN_OAUTH_KEYS:
            if not merged.get(key) and val:
                merged[key] = val
            continue
        if key == "scopes":
            if catalog_overrides or not merged.get("scopes"):
                merged["scopes"] = val
            continue
        if key == "authorize_params":
            if catalog_overrides:
                merged["authorize_params"] = dict(val) if isinstance(val, dict) else {}
            else:
                existing = merged.get("authorize_params")
                if not isinstance(existing, dict) or not existing:
                    merged["authorize_params"] = (
                        dict(val) if isinstance(val, dict) else {}
                    )
                elif isinstance(val, dict):
                    for pk, pv in val.items():
                        existing.setdefault(pk, pv)
                    merged["authorize_params"] = existing
            continue
        if catalog_overrides and key in _CATALOG_OAUTH_OVERRIDE_KEYS:
            merged[key] = val
        elif merged.get(key) in (None, ""):
            merged[key] = val
    return merged


def _parse_runtime_env_alias_entries(raw: Any) -> List[Tuple[str, List[str]]]:
    """Normalizza ``runtime_env_aliases`` (lista di dict o mappa dest -> sorgenti)."""
    out: List[Tuple[str, List[str]]] = []
    if isinstance(raw, dict):
        for dest, sources in raw.items():
            if not isinstance(dest, str) or not dest.strip():
                continue
            if isinstance(sources, str):
                out.append((dest, [sources]))
            elif isinstance(sources, list):
                out.append(
                    (
                        dest,
                        [
                            str(s)
                            for s in sources
                            if isinstance(s, str) and str(s).strip()
                        ],
                    )
                )
        return out
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, dict):
                continue
            dest = row.get("env_key") or row.get("key") or row.get("target")
            if not isinstance(dest, str) or not dest.strip():
                continue
            sources = (
                row.get("from_env_keys") or row.get("from_keys") or row.get("from")
            )
            if isinstance(sources, str):
                out.append((dest, [sources]))
            elif isinstance(sources, list):
                out.append(
                    (
                        dest,
                        [
                            str(s)
                            for s in sources
                            if isinstance(s, str) and str(s).strip()
                        ],
                    )
                )
    return out


def _env_value_nonempty(val: Any) -> bool:
    return val is not None and str(val).strip() != ""


def apply_runtime_env_aliases(
    env: Dict[str, Any],
    registry_server_name: str,
    server_config: Dict[str, Any],
    catalog: Dict[str, Any] | None = None,
) -> None:
    """
    Applica ``runtime_env_aliases`` dalla riga catalogo del server (se presenti).

    Utile quando documentazione / template (Hermes, Claude Code, hub n8n) usano nomi env diversi
    da quelli che il processo MCP si aspetta: si dichiara la mappa nel YAML del connettore,
    senza codice dedicato per integrazione.
    """
    data = catalog if catalog is not None else load_mcp_connector_catalog()
    row = resolve_connector_row_for_mcp_server(
        registry_server_name, server_config, data
    )
    if not row:
        return
    entries = _parse_runtime_env_alias_entries(row.get("runtime_env_aliases"))
    if not entries:
        return
    for dest, source_keys in entries:
        if _env_value_nonempty(env.get(dest)):
            continue
        for src in source_keys:
            if _env_value_nonempty(env.get(src)):
                env[dest] = str(env[src])
                break


def load_mcp_connector_catalog() -> Dict[str, Any]:
    """Carica catalogo da config/ o, in assenza, da config_std/."""
    path = resolve_connector_catalog_path()
    if not path:
        logger.warning(
            "mcp connector catalog missing: %s and %s",
            connector_catalog_path(),
            connector_catalog_std_path(),
        )
        return {"version": 1, "connectors": []}
    try:
        import yaml

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {"version": 1, "connectors": []}
        con = data.get("connectors")
        if not isinstance(con, list):
            data["connectors"] = []
        return data
    except Exception as e:
        logger.error("failed to load connector catalog: %s", e)
        return {"version": 1, "connectors": [], "error": str(e)}
