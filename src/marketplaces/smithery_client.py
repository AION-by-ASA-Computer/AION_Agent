"""
Smithery API client for Zero-Install MCP server discovery and schema fetching.
Ref: https://api.smithery.ai
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("aion.marketplaces.smithery")

SMITHERY_API_BASE = "https://api.smithery.ai"


def _get_api_key() -> str:
    return (
        os.getenv("AION_SMITHERY_API_KEY") or os.getenv("SMITHERY_API_KEY") or ""
    ).strip()


def _get_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "AION-Agent/1.0",
    }
    key = _get_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-Smithery-Api-Key"] = key
    return headers


def _is_github_url(url: str) -> bool:
    """True se l'URL appartiene al dominio github.com."""
    if not url:
        return False
    return "github.com/" in url.lower()


def has_smithery_proprietary_auth(s: Dict[str, Any], q_name: str = "") -> bool:
    """
    Rileva se un server MCP usa l'autenticazione proprietaria di Smithery
    (es. bySmithery con OAuth hosted su *.run.tools, endpoint proxy proprietario).
    """
    # 1. Server ufficiali creati/ospitati da Smithery con OAuth proprietario
    if bool(s.get("bySmithery")):
        return True

    raw_hp = (s.get("homepage") or "").lower()
    raw_repo = (
        s.get("repository")
        or s.get("repositoryUrl")
        or s.get("githubUrl")
        or s.get("repoUrl")
        or ""
    ).lower()
    dep_url = (s.get("deploymentUrl") or "").lower()

    # 2. Homepage o deployment su smithery.ai / run.tools senza repository sorgente pubblico
    if not _is_github_url(raw_repo) and not _is_github_url(raw_hp):
        if "smithery.ai" in raw_hp or "run.tools" in dep_url:
            return True

    # 3. Connessioni che puntano a proxy OAuth run.tools senza schema API key
    connections = s.get("connections") or []
    if isinstance(connections, list):
        for conn in connections:
            if isinstance(conn, dict):
                c_url = (conn.get("deploymentUrl") or "").lower()
                c_props = conn.get("configSchema", {}).get("properties") if isinstance(conn.get("configSchema"), dict) else None
                if "run.tools" in c_url and not c_props and not _is_github_url(raw_repo):
                    return True

    return False


def search_smithery_servers(
    query: str = "", *, page: int = 1, page_size: int = 24
) -> List[Dict[str, Any]]:
    """
    Search or list MCP servers from Smithery registry.
    Smithery viene utilizzato come catalogo per la visualizzazione/scoperta:
    - I server con autenticazione proprietaria di Smithery (OAuth run.tools) vengono esclusi.
    - Vengono mantenuti unicamente i server standard di GitHub e quelli verificati.
    """
    url = f"{SMITHERY_API_BASE}/servers"
    params: Dict[str, Any] = {
        "pageSize": page_size,
        "page": page,
    }
    if query and query.strip():
        params["q"] = query.strip()

    try:
        resp = requests.get(url, params=params, headers=_get_headers(), timeout=12)
        if resp.status_code != 200:
            logger.warning(
                "Smithery search failed (HTTP %s): %s",
                resp.status_code,
                resp.text[:200],
            )
            return []

        data = resp.json()
        servers = data.get("servers") if isinstance(data, dict) else data
        if not isinstance(servers, list):
            return []

        results: List[Dict[str, Any]] = []
        for s in servers:
            if not isinstance(s, dict):
                continue
            q_name = (s.get("qualifiedName") or s.get("name") or "").strip()
            if not q_name:
                continue

            # 1. Escludi server con autenticazione proprietaria di Smithery
            if has_smithery_proprietary_auth(s, q_name):
                continue

            # Determina URL del repository sorgente o homepage
            raw_repo = (
                s.get("repository")
                or s.get("repositoryUrl")
                or s.get("githubUrl")
                or s.get("repoUrl")
                or ""
            ).strip()
            raw_hp = (s.get("homepage") or "").strip()

            if _is_github_url(raw_repo):
                repo_url = raw_repo
                is_github = True
            elif _is_github_url(raw_hp):
                repo_url = raw_hp
                is_github = True
            elif not raw_hp and "/" in q_name and not q_name.startswith("@") and not q_name.startswith("smithery/"):
                repo_url = f"https://github.com/{q_name}"
                is_github = True
            elif raw_hp:
                repo_url = raw_hp
                is_github = False
            else:
                repo_url = f"https://smithery.ai/server/{q_name}"
                is_github = False

            is_verified = bool(s.get("verified"))

            # 2. Mantieni solo quelli standard di GitHub e quelli verificati
            if not (is_github or is_verified):
                continue

            # Smithery funge da catalogo di visualizzazione (nessun proxy oauth remoto)
            results.append(
                {
                    "id": f"smithery:{q_name}",
                    "qualified_name": q_name,
                    "name": s.get("displayName") or q_name,
                    "namespace": s.get("namespace")
                    or (q_name.split("/")[0] if "/" in q_name else ""),
                    "description": s.get("description") or "",
                    "icon_url": s.get("iconUrl") or "",
                    "source": "Smithery",
                    "verified": is_verified,
                    "use_count": s.get("useCount") or 0,
                    "remote": False,
                    "deployment_url": "",
                    "homepage": repo_url,
                    "url": repo_url,
                    "install_type": "git" if is_github else "catalog",
                    "has_smithery_schema": True,
                    "schema_source": "smithery",
                    "is_github": is_github,
                    "catalog_only": not is_github,
                }
            )
        return results
    except Exception as exc:
        logger.error("Smithery search request failed: %s", exc)
        return []


def get_smithery_server_details(qualified_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch full details and configSchema for a Smithery MCP server.
    `qualified_name` can be e.g. "devopam/mcpg" or "prisma".
    """
    raw_name = qualified_name.removeprefix("smithery:").strip().strip("/")
    url = f"{SMITHERY_API_BASE}/servers/{raw_name}"

    try:
        resp = requests.get(url, headers=_get_headers(), timeout=12)
        if resp.status_code != 200:
            logger.warning(
                "Smithery get details failed for %s (HTTP %s): %s",
                raw_name,
                resp.status_code,
                resp.text[:200],
            )
            return None
        return resp.json()
    except Exception as exc:
        logger.error("Smithery get details request failed for %s: %s", raw_name, exc)
        return None


def extract_normalized_envs_from_schema(
    details: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Normalize Smithery configSchema into structured fields for the dynamic UI wizard.
    Output items: {
        "key": str,
        "description": str,
        "required": bool,
        "is_secret": bool,
        "default": str,
        "type": str
    }
    """
    fields: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()

    connections = details.get("connections") or []
    config_schema: Dict[str, Any] = (
        details.get("configSchema")
        or (
            connections[0].get("configSchema")
            if isinstance(connections, list)
            and connections
            and isinstance(connections[0], dict)
            else {}
        )
        or (
            details.get("server", {}).get("configSchema")
            if isinstance(details.get("server"), dict)
            else {}
        )
        or details.get("schema")
        or {}
    )

    properties = config_schema.get("properties") or {}
    required_list = set(config_schema.get("required") or [])

    secret_keywords = (
        "key",
        "token",
        "secret",
        "password",
        "auth",
        "credential",
        "pwd",
        "api_key",
        "apikey",
        "bearer",
        "database_url",
    )

    for raw_key, prop in properties.items():
        if not isinstance(prop, dict):
            continue

        # Determine secret heuristic
        key_lower = raw_key.lower()
        title_lower = str(prop.get("title") or "").lower()
        desc_lower = str(prop.get("description") or "").lower()

        is_secret = any(kw in key_lower or kw in title_lower for kw in secret_keywords)
        if "url" in key_lower and not any(
            kw in key_lower
            for kw in ("password", "token", "secret", "database_url", "db_url")
        ):
            is_secret = False

        description = prop.get("description") or prop.get("title") or ""
        default_val = prop.get("default")
        default_str = str(default_val) if default_val is not None else ""

        is_req = raw_key in required_list

        fields.append(
            {
                "key": raw_key,
                "description": description,
                "required": is_req,
                "is_secret": is_secret,
                "default": default_str,
                "type": prop.get("type") or "string",
            }
        )
        seen_keys.add(raw_key)

    return fields
