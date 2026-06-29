"""
Rilevamento automatico credenziali / env per server MCP arbitrari (senza catalogo curato).

Fonti: README, .env.example, sorgenti, env già presenti nel registry.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .mcp_server_files import read_mcp_server_files, resolve_mcp_server_dir

# ---------------------------------------------------------------------------
# TTL cache for probe_remote_url_sync – avoids re-probing the same URL
# during a single request (the function is called 2-3× per integration).
# ---------------------------------------------------------------------------
_PROBE_CACHE: dict[str, tuple[float, Dict[str, Any]]] = {}
_PROBE_CACHE_TTL: int = int(os.environ.get("AION_INTEGRATIONS_PROBE_TTL", "60"))

# ---------------------------------------------------------------------------
# Per-slug cache for discover_mcp_credentials – eliminates the 2-3 redundant
# calls per integration during the integrations-list endpoint.
# ---------------------------------------------------------------------------
_DISCOVERY_CACHE: dict[str, CredentialDiscoveryResult] = {}

# Timeout for HTTP probes – reduced from 15 s to a configurable value
# (default 5 s).  Page-load probing does not need a full 15 s wait.
_PROBE_TIMEOUT: float = float(os.environ.get("AION_INTEGRATIONS_PROBE_TIMEOUT", "5"))

# Env di runtime / framework — non chiedere in chat-ui
_SKIP_ENV = frozenset(
    {
        "NODE_ENV",
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "LANG",
        "LC_ALL",
        "PWD",
        "TMPDIR",
        "PYTHONPATH",
        "PYTHONUNBUFFERED",
        "CI",
        "DEBUG",
        "LOG_LEVEL",
        "NO_COLOR",
        "FORCE_COLOR",
        "TERM",
        "PORT",
        "HOST",
        "HOSTNAME",
        "DOTENV_CONFIG_PATH",
        "FASTMCP_LOG_LEVEL",
        "FASTMCP_SHOW_SERVER_BANNER",
        "FASTMCP_CHECK_FOR_UPDATES",
        "MCP_TRANSPORT",
        "UV_THREADPOOL_SIZE",
    }
)

_SKIP_PREFIXES = ("AION_", "FASTMCP_", "MCP_LOG", "VITE_", "NEXT_PUBLIC_")

_CREDENTIAL_KEY_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY|CLIENT_SECRET|"
    r"REFRESH|CREDENTIAL|AUTH|EMAIL|IMAP|SMTP|BEARER|OAUTH)",
    re.I,
)

_ENV_PATTERNS = [
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)", re.M),
    re.compile(r"""process\.env\[['"]([A-Z][A-Z0-9_]*)['"]\]""", re.M),
    re.compile(r"""os\.environ\[['"]([A-Z][A-Z0-9_]*)['"]\]""", re.M),
    re.compile(r"""os\.getenv\(\s*['"]([A-Z][A-Z0-9_]*)['"]""", re.M),
    re.compile(r"""['"]([A-Z][A-Z0-9_]{2,})['"]\s*:\s*process\.env""", re.M),
    re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*:\s*z\.", re.M),
    re.compile(r"\b([A-Z][A-Z0-9_]{3,})\s*:\s*z\.string", re.M),
    re.compile(r'"([A-Z][A-Z0-9_]{3,})"\s*:\s*"', re.M),
    re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=", re.M),
]

_AION_USER_KEY_RE = re.compile(r"^\$\{AION_USER_[A-Z0-9_]+__([A-Z0-9_]+)\}$")
_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Z][A-Z0-9_]+)\}$")

_CONFIG_FILE_HINTS = re.compile(
    r"config\.toml|\.config/|xdg|XDG_CONFIG|credentials?\s+file|file\s+di\s+configurazione",
    re.I,
)


@dataclass
class CredentialDiscoveryResult:
    env_keys: List[str] = field(default_factory=list)
    schema: List[Dict[str, Any]] = field(default_factory=list)
    credential_mode_hint: str = "none"
    sources: List[str] = field(default_factory=list)
    config_file_auth: bool = False
    has_env_auth: bool = False
    remote_auth_type: Optional[str] = None
    remote_connect_url: Optional[str] = None
    remote_docs_url: Optional[str] = None
    remote_hint: Optional[str] = None
    remote_error: Optional[str] = None
    remote_oauth_provider: Optional[str] = None
    remote_oauth_server: Optional[str] = None
    remote_oauth_token_url: Optional[str] = None


def _should_skip_env(key: str) -> bool:
    if not key or len(key) < 2:
        return True
    if key in _SKIP_ENV:
        return True
    return any(key.startswith(p) for p in _SKIP_PREFIXES)


def _is_credential_key(key: str) -> bool:
    return bool(_CREDENTIAL_KEY_RE.search(key))


def _field_type(key: str) -> str:
    return "password" if _is_credential_key(key) else "text"


def _keys_from_text(text: str) -> Set[str]:
    found: Set[str] = set()
    if not text:
        return found
    for pat in _ENV_PATTERNS:
        for m in pat.finditer(text):
            k = m.group(1)
            if k and not _should_skip_env(k):
                found.add(k)
    return found


def _keys_from_registry_env(env: Dict[str, Any]) -> Set[str]:
    """Chiavi env del registry (nome variabile MCP), non il testo interno ai placeholder."""
    found: Set[str] = set()
    for key, val in (env or {}).items():
        if isinstance(key, str) and key.strip() and not _should_skip_env(key.strip()):
            found.add(key.strip())
        if isinstance(val, str):
            s = val.strip()
            m = _AION_USER_KEY_RE.match(s)
            if m:
                found.add(m.group(1))
                continue
            m2 = _ENV_PLACEHOLDER_RE.match(s)
            if m2:
                inner = m2.group(1)
                if inner.startswith("AION_USER_"):
                    continue
                if _is_credential_key(inner):
                    found.add(inner)
    return found


def _label_for_env_key(key: str) -> str:
    for prefix in ("MCP_EMAIL_SERVER_", "MCP_"):
        if key.startswith(prefix) and len(key) > len(prefix):
            return key[len(prefix) :].replace("_", " ").strip().title()
    return key.replace("_", " ").title()


def _schema_from_keys(keys: List[str]) -> List[Dict[str, Any]]:
    schema: List[Dict[str, Any]] = []
    for k in keys:
        if k.startswith("AION_USER_"):
            continue
        schema.append(
            {
                "key": k,
                "label": _label_for_env_key(k),
                "type": _field_type(k),
                "required": True,
                "description": None,
            }
        )
    return schema


def classify_from_headers(
    headers: List[Dict[str, Any]], remote: Dict[str, Any], meta: Dict[str, Any]
) -> Dict[str, Any]:
    has_bearer = False
    has_basic = False
    has_oauth = False

    for h in headers:
        if not isinstance(h, dict):
            continue
        name = str(h.get("name") or "").lower()
        value = str(h.get("value") or "").lower()
        if "bearer" in value or "bearer" in name:
            has_bearer = True
        elif "basic" in value or "basic" in name:
            has_basic = True
        elif "oauth" in value or "oauth" in name or "authorization_uri" in value:
            has_oauth = True

    connect_url = meta.get("connect") or None
    url = remote.get("url")

    if has_oauth:
        return {
            "type": "oauth2",
            "url": url,
            "connectUrl": connect_url,
            "credential_mode": "per_user",
            "credential_schema": [
                {
                    "key": "OAUTH_TOKEN",
                    "label": "OAuth Token",
                    "type": "oauth",
                    "required": True,
                }
            ],
        }
    if has_bearer:
        return {
            "type": "api-key",
            "url": url,
            "connectUrl": connect_url,
            "credential_mode": "per_user",
            "credential_schema": [
                {
                    "key": "API_KEY",
                    "label": "API Key",
                    "type": "password",
                    "required": True,
                }
            ],
        }
    if has_basic:
        return {
            "type": "basic",
            "url": url,
            "connectUrl": connect_url,
            "credential_mode": "per_user",
            "credential_schema": [
                {
                    "key": "BASIC_AUTH",
                    "label": "Basic Auth Credentials",
                    "type": "password",
                    "required": True,
                }
            ],
        }
    return {
        "type": "api-key",
        "url": url,
        "connectUrl": connect_url,
        "credential_mode": "per_user",
        "credential_schema": [
            {"key": "API_KEY", "label": "API Key", "type": "password", "required": True}
        ],
    }


def extract_url_from_www_authenticate(www_auth: str, param_name: str) -> Optional[str]:
    import re

    pattern = rf'{param_name}\s*=\s*(?:"([^"]+)"|([^,\s]+))'
    match = re.search(pattern, www_auth, re.IGNORECASE)
    if match:
        return match.group(1) or match.group(2)
    return None


def detect_oauth_provider(url: str = "") -> str:
    url_lower = url.lower()
    if "google" in url_lower:
        return "google"
    if "github" in url_lower:
        return "github"
    if "microsoft" in url_lower or "microsoftonline" in url_lower:
        return "microsoft"
    if "auth0" in url_lower:
        return "auth0"
    return "generic"


def get_url_origin(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def probe_remote_url_sync(url: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    # --- TTL cache ----------------------------------------------------------
    now = time.monotonic()
    cached = _PROBE_CACHE.get(url)
    if cached is not None:
        ts, result = cached
        if now - ts < _PROBE_CACHE_TTL:
            return result
        else:
            del _PROBE_CACHE[url]
    # -------------------------------------------------------------------------
    import requests

    try:
        response = requests.get(url, timeout=_PROBE_TIMEOUT)

        if response.status_code == 200:
            return {
                "type": "none",
                "url": url,
                "credential_mode": "none",
                "credential_schema": [],
            }
        elif response.status_code == 401:
            www_auth = response.headers.get("WWW-Authenticate") or ""
            connect_url = meta.get("connect") or None

            # 3a. Ha resource_metadata -> segui il link (RFC 9728)
            resource_meta = extract_url_from_www_authenticate(
                www_auth, "resource_metadata"
            )
            if resource_meta:
                try:
                    meta_res = requests.get(resource_meta, timeout=_PROBE_TIMEOUT)
                    if meta_res.status_code == 200:
                        doc = meta_res.json()
                        auth_servers = doc.get("authorization_servers") or []
                        issuer = auth_servers[0] if auth_servers else ""
                        if issuer:
                            token_url = None
                            try:
                                wk_url = f"{issuer.rstrip('/')}/.well-known/oauth-authorization-server"
                                wk_res = requests.get(wk_url, timeout=5.0)
                                if wk_res.status_code != 200:
                                    wk_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
                                    wk_res = requests.get(wk_url, timeout=5.0)
                                if wk_res.status_code == 200:
                                    token_url = wk_res.json().get("token_endpoint")
                            except Exception:
                                pass

                            provider = detect_oauth_provider(issuer)
                            return {
                                "type": "oauth2",
                                "url": url,
                                "hint": www_auth,
                                "connectUrl": connect_url,
                                "credential_mode": "per_user",
                                "oauth_provider": provider,
                                "oauth_server": issuer,
                                "oauth_token_url": token_url
                                or f"{issuer.rstrip('/')}/token",
                                "credential_schema": [
                                    {
                                        "key": "OAUTH_TOKEN",
                                        "label": "OAuth Token",
                                        "type": "oauth",
                                        "required": True,
                                    }
                                ],
                            }
                except Exception:
                    pass

            # 3b. Ha authorization_uri diretto
            auth_uri = extract_url_from_www_authenticate(www_auth, "authorization_uri")
            if auth_uri:
                provider = detect_oauth_provider(auth_uri)
                token_url = auth_uri.replace("/auth", "/token").replace(
                    "/authorize", "/token"
                )
                return {
                    "type": "oauth2",
                    "url": url,
                    "hint": www_auth,
                    "connectUrl": connect_url,
                    "credential_mode": "per_user",
                    "oauth_provider": provider,
                    "oauth_server": auth_uri,
                    "oauth_token_url": token_url,
                    "credential_schema": [
                        {
                            "key": "OAUTH_TOKEN",
                            "label": "OAuth Token",
                            "type": "oauth",
                            "required": True,
                        }
                    ],
                }

            # 3c. Prova /.well-known/oauth-authorization-server
            try:
                origin_url = get_url_origin(url)
                wk_url = f"{origin_url}/.well-known/oauth-authorization-server"
                wk_res = requests.get(wk_url, timeout=_PROBE_TIMEOUT)
                if wk_res.status_code == 200:
                    doc = wk_res.json()
                    issuer = doc.get("issuer")
                    token_url = doc.get("token_endpoint")
                    if issuer:
                        provider = detect_oauth_provider(issuer)
                        return {
                            "type": "oauth2",
                            "url": url,
                            "hint": www_auth,
                            "connectUrl": connect_url,
                            "credential_mode": "per_user",
                            "oauth_provider": provider,
                            "oauth_server": issuer,
                            "oauth_token_url": token_url
                            or f"{issuer.rstrip('/')}/token",
                            "credential_schema": [
                                {
                                    "key": "OAUTH_TOKEN",
                                    "label": "OAuth Token",
                                    "type": "oauth",
                                    "required": True,
                                }
                            ],
                        }
            except Exception:
                pass

            # Fallback 401
            if "bearer" in www_auth.lower():
                return {
                    "type": "api-key",
                    "url": url,
                    "hint": www_auth,
                    "connectUrl": connect_url,
                    "credential_mode": "per_user",
                    "credential_schema": [
                        {
                            "key": "API_KEY",
                            "label": "API Key",
                            "type": "password",
                            "required": True,
                        }
                    ],
                }
            elif "basic" in www_auth.lower():
                return {
                    "type": "basic",
                    "url": url,
                    "hint": www_auth,
                    "connectUrl": connect_url,
                    "credential_mode": "per_user",
                    "credential_schema": [
                        {
                            "key": "BASIC_AUTH",
                            "label": "Basic Auth Credentials",
                            "type": "password",
                            "required": True,
                        }
                    ],
                }
            else:
                return {
                    "type": "unknown",
                    "url": url,
                    "hint": www_auth,
                    "connectUrl": connect_url,
                    "credential_mode": "per_user",
                    "credential_schema": [
                        {
                            "key": "API_KEY",
                            "label": "API Key / Token",
                            "type": "password",
                            "required": True,
                        }
                    ],
                }
        elif response.status_code == 403:
            return {
                "type": "unknown",
                "url": url,
                "credential_mode": "per_user",
                "credential_schema": [
                    {
                        "key": "API_KEY",
                        "label": "Token / API Key",
                        "type": "password",
                        "required": True,
                    }
                ],
            }
        else:
            return {
                "type": "unreachable",
                "url": url,
                "error": f"HTTP {response.status_code}",
            }
    except Exception as e:
        return {"type": "unreachable", "url": url, "error": str(e)}


def _extract_remote_bridge_token_key(cfg: dict) -> Optional[str]:
    """Estrae il nome della env var dal --header Bearer ${VAR} negli args di mcp-remote."""
    args = cfg.get("args") or []
    import re

    for i, arg in enumerate(args):
        if arg == "--header" and i + 1 < len(args):
            header_val = args[i + 1]
            m = re.search(r"\$\{([A-Z0-9_]+)\}", header_val)
            if m:
                return m.group(1)
    return None


def discover_mcp_credentials(
    server_slug: str,
    server_config: Optional[Dict[str, Any]] = None,
) -> CredentialDiscoveryResult:
    """
    Analizza file installati e registry per proporre schema credenziali e modalità.
    """
    # Fast path: reuse discovery result for the same slug within this request.
    cached = _DISCOVERY_CACHE.get(server_slug)
    if cached is not None:
        return cached

    cfg = server_config or {}

    # Rilevamento server remoti (SSE o remote-bridge)
    is_remote = cfg.get("aion_market_install") == "remote" or cfg.get("type") in (
        "sse",
        "remote-bridge",
    )
    if is_remote:
        remotes = cfg.get("remotes") or []
        url = cfg.get("remote_url") or cfg.get("url")
        remote = None
        if remotes:
            for r in remotes:
                if isinstance(r, dict) and r.get("type") in (
                    "sse",
                    "streamable-http",
                    "streamable_http",
                ):
                    remote = r
                    break
            if not remote and remotes:
                remote = remotes[0]
        if not remote and url:
            remote = {"url": url, "type": "sse", "headers": []}

        if not remote:
            _res = CredentialDiscoveryResult(
                env_keys=[],
                schema=[],
                credential_mode_hint="none",
                sources=["remote_discovery"],
                remote_auth_type="no-remote",
            )
            _DISCOVERY_CACHE[server_slug] = _res
            return _res

        headers = remote.get("headers") or []
        meta = cfg.get("_meta", {}).get(
            "io.modelcontextprotocol.registry/publisher-provided", {}
        )

        classified = None
        if headers:
            classified = classify_from_headers(headers, remote, meta)

        probe_url = cfg.get("remote_url") or remote.get("url") or url
        if probe_url:
            probe_res = probe_remote_url_sync(probe_url, meta)
            # Store in TTL cache so repeated calls with the same URL
            # during this request skip the HTTP round-trip.
            _PROBE_CACHE[probe_url] = (time.monotonic(), probe_res)
        else:
            probe_res = {"type": "unreachable", "error": "Missing remote URL"}

        if classified:
            if probe_res.get("type") == "unreachable":
                final_res = probe_res
            else:
                final_res = classified
                if "hint" not in final_res and "hint" in probe_res:
                    final_res["hint"] = probe_res["hint"]
        else:
            final_res = probe_res

        auth_type = final_res.get("type", "unknown")
        mode_hint = final_res.get("credential_mode", "per_user")
        schema = final_res.get("credential_schema") or []

        if cfg.get("type") == "remote-bridge":
            token_key = _extract_remote_bridge_token_key(cfg)
            if token_key:
                db_key = token_key
                if "__" in token_key:
                    db_key = token_key.split("__", 1)[1]
                elif token_key.startswith("AION_USER_"):
                    db_key = token_key[len("AION_USER_") :]

                if schema:
                    schema = [dict(s) for s in schema]
                    for s in schema:
                        s["key"] = db_key
                else:
                    schema = [
                        {
                            "key": db_key,
                            "label": "Token / API Key",
                            "type": "password",
                            "required": True,
                        }
                    ]
                    mode_hint = "per_user"
                    if auth_type == "unknown" or auth_type == "unreachable":
                        auth_type = "api-key"

        env_keys = [s.get("key") for s in schema]

        _res = CredentialDiscoveryResult(
            env_keys=env_keys,
            schema=schema,
            credential_mode_hint=mode_hint,
            sources=["remote_probe" + ("+headers" if headers else "")],
            remote_auth_type=auth_type,
            remote_connect_url=final_res.get("connectUrl"),
            remote_docs_url=final_res.get("docsUrl") or meta.get("docs"),
            remote_hint=final_res.get("hint"),
            remote_error=final_res.get("error"),
            remote_oauth_provider=final_res.get("oauth_provider"),
            remote_oauth_server=final_res.get("oauth_server"),
            remote_oauth_token_url=final_res.get("oauth_token_url"),
            has_env_auth=(mode_hint != "none" and auth_type != "unreachable"),
        )
        _DISCOVERY_CACHE[server_slug] = _res
        return _res

    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    keys: Set[str] = set()
    sources: List[str] = []

    registry_keys = _keys_from_registry_env(env)
    if registry_keys:
        keys |= registry_keys
        sources.append("registry")

    mcp_dir = resolve_mcp_server_dir(server_slug)
    if mcp_dir:
        for env_name in (".env.example", ".env.sample", ".env.template"):
            ef = mcp_dir / env_name
            if ef.is_file():
                keys |= _keys_from_text(
                    ef.read_text(encoding="utf-8", errors="replace")
                )
                sources.append(env_name)
                break

        for src in ("index.ts", "index.js", "server.ts", "server.py", "main.ts"):
            sf = mcp_dir / src
            if sf.is_file():
                keys |= _keys_from_text(
                    sf.read_text(encoding="utf-8", errors="replace")
                )
                sources.append(src)
                break

    readme_text = ""
    if mcp_dir and (mcp_dir / "README.md").is_file():
        readme_text = (mcp_dir / "README.md").read_text(
            encoding="utf-8", errors="replace"
        )
        keys |= _keys_from_text(readme_text)
        sources.append("README.md")

    # Solo chiavi che sembrano credenziali o config server (host/port)
    cred_keys = sorted(
        k
        for k in keys
        if not k.startswith("AION_USER_")
        and (
            _is_credential_key(k)
            or k.endswith(("_HOST", "_PORT", "_URL", "_URI", "_SSL"))
        )
    )

    config_file_auth = bool(readme_text and _CONFIG_FILE_HINTS.search(readme_text))
    has_env_auth = len(cred_keys) > 0

    mode_hint = "none"
    if has_env_auth:
        mode_hint = "per_user"
    elif config_file_auth and not has_env_auth:
        mode_hint = "none"

    _res = CredentialDiscoveryResult(
        env_keys=cred_keys,
        schema=_schema_from_keys(cred_keys),
        credential_mode_hint=mode_hint,
        sources=sources,
        config_file_auth=config_file_auth,
        has_env_auth=has_env_auth,
    )
    _DISCOVERY_CACHE[server_slug] = _res
    return _res


def merge_schema_sources(
    *,
    catalog_schema: List[Dict[str, Any]],
    discovered_schema: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Catalogo opzionale (config/) + discovery; discovery riempie i buchi."""
    if catalog_schema and not discovered_schema:
        return catalog_schema
    if discovered_schema and not catalog_schema:
        return discovered_schema
    if not catalog_schema and not discovered_schema:
        return []
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in discovered_schema:
        k = str(row.get("key") or "").strip()
        if k:
            by_key[k] = row
    for row in catalog_schema:
        k = str(row.get("key") or "").strip()
        if k:
            by_key[k] = row
    return [by_key[k] for k in sorted(by_key.keys())]
