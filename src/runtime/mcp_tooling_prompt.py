"""
Linee guida MCP nel system prompt dell'agente.

Il protocollo MCP espone i tool con ``name``, ``description`` e ``inputSchema`` via ``list_tools``;
molti server non ripetono nei tool la documentazione estesa che tengono in ``docs/`` sul repository Git.
Il Model Context Protocol prevede anche ``resources`` e ``prompts`` opzionali; AION oggi non importa
automaticamente file Markdown da clone/npm: si integra tramite testo curato nel catalogo connettori
(``agent_guidance`` + URL di riferimento).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..mcp_connector_catalog import infer_connector_id_for_registry_name, load_mcp_connector_catalog


def _connector_by_id_map(catalog: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in catalog.get("connectors") or []:
        if isinstance(c, dict) and c.get("id"):
            out[str(c["id"]).lower()] = c
    return out


def resolve_connector_id_for_server(
    server_key: str, cfg: Optional[Dict[str, Any]], catalog: Dict[str, Any]
) -> Optional[str]:
    if cfg:
        cid = (cfg.get("aion_connector_id") or "").strip()
        if cid:
            return cid
    return infer_connector_id_for_registry_name(server_key, catalog)


def build_mcp_tooling_prompt_section(
    mcp_servers: List[str],
    get_server_config: Callable[[str], Optional[Dict[str, Any]]],
) -> str:
    """
    Costruisce un blocco markdown da appendere al system prompt se il catalogo definisce ``agent_guidance``.
    ``get_server_config`` è tipicamente ``mcp_manager.get_server_config``.
    """
    if not mcp_servers:
        return ""
    catalog = load_mcp_connector_catalog()
    by_id = _connector_by_id_map(catalog)
    blocks: list[str] = []
    seen: set[str] = set()
    for srv in mcp_servers:
        cfg = get_server_config(srv) or {}
        cid = resolve_connector_id_for_server(srv, cfg, catalog)
        if not cid:
            continue
        key = cid.lower()
        if key in seen:
            continue
        seen.add(key)
        con = by_id.get(key)
        if not con:
            continue
        guidance = (con.get("agent_guidance") or "").strip()
        if not guidance:
            continue
        title = con.get("title") or cid
        doc_url = (con.get("mcp_upstream_docs_url") or con.get("official_doc_url") or "").strip()
        header = f"### MCP: {title} (server registry: `{srv}`)\n"
        body = guidance
        if doc_url:
            body += f"\n\nExtended documentation (vendor): {doc_url}"
        blocks.append(header + body)
    if not blocks:
        return ""
    intro = (
        "## Strumenti MCP — come usarli\n"
        "Each MCP tool is already listed in the model context with **short description** and **parameter schema** "
        "(standard MCP `list_tools`). The notes below are a curated **conceptual map** in AION: "
        "they do not replace required parameters of individual tools.\n\n"
    )
    return intro + "\n\n".join(blocks)
