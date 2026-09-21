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


def search_smithery_servers(
    query: str = "", *, page: int = 1, page_size: int = 24
) -> List[Dict[str, Any]]:
    """
    Search or list MCP servers from Smithery registry.
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

            repo_url = (
                s.get("homepage")
                or s.get("repository")
                or s.get("repositoryUrl")
                or s.get("githubUrl")
                or s.get("repoUrl")
                or ""
            ).strip()

            if not repo_url:
                if "/" in q_name and not q_name.startswith("@"):
                    repo_url = f"https://github.com/{q_name}"
                else:
                    repo_url = f"https://smithery.ai/server/{q_name}"

            is_remote = bool(s.get("remote")) or bool(s.get("deploymentUrl"))
            deployment_url = (s.get("deploymentUrl") or "").strip()
            if not deployment_url and is_remote:
                clean_host_slug = q_name.replace("/", "--").replace("@", "")
                deployment_url = f"https://{clean_host_slug}.run.tools"

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
                    "verified": bool(s.get("verified")),
                    "use_count": s.get("useCount") or 0,
                    "remote": is_remote,
                    "deployment_url": deployment_url,
                    "homepage": repo_url,
                    "url": deployment_url
                    if (is_remote and deployment_url)
                    else repo_url,
                    "install_type": "remote" if is_remote else "zero-install",
                    "has_smithery_schema": True,
                    "schema_source": "smithery",
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
