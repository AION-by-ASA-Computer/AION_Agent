"""Load curated MCP connector catalog (YAML) for admin UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("aion.mcp_connector_catalog")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def connector_catalog_path() -> Path:
    """Catalogo opzionale (override tenant). La discovery automatica non dipende da questo file."""
    return _repo_root() / "config" / "mcp_connector_catalog.yaml"


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
    """Carica catalogo opzionale da config/mcp_connector_catalog.yaml (può essere vuoto)."""
    path = connector_catalog_path()
    if not path.exists():
        logger.warning("mcp connector catalog missing: %s", path)
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
