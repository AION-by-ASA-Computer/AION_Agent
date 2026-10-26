"""Remote MCP bridge registry helpers (mcp-remote stdio proxy)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Versione di mcp-remote: deve coincidere con docker/package.mcp-remote.json
# (tutto il traffico verso i broker remoti passa da qui).
MCP_REMOTE_VERSION = "0.1.49"

MCP_REMOTE_PROXY_MARKERS = (
    "node_modules/mcp-remote/dist/proxy.js",
    "mcp-remote/dist/proxy.js",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_mcp_remote_proxy_arg(arg: str) -> bool:
    if not isinstance(arg, str):
        return False
    norm = arg.replace("\\", "/")
    return any(
        norm.endswith(marker) or marker in norm for marker in MCP_REMOTE_PROXY_MARKERS
    )


def mcp_remote_proxy_path() -> Optional[str]:
    """Absolute path to locally installed mcp-remote proxy.js, if present."""
    for root in (Path.cwd(), _repo_root()):
        candidate = root / "node_modules" / "mcp-remote" / "dist" / "proxy.js"
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def remote_bridge_tail_args(args: List[str]) -> List[str]:
    """Args after the optional proxy.js entrypoint."""
    if args and is_mcp_remote_proxy_arg(args[0]):
        return list(args[1:])
    return list(args)


def resolve_remote_bridge_spawn(config: Dict[str, Any]) -> Tuple[str, List[str]]:
    """
    Spawn command for remote-bridge MCP servers.

    Prefer local ``node_modules/mcp-remote`` (Docker image); fall back to
    ``npx -y mcp-remote@<MCP_REMOTE_VERSION>`` when the package is not installed under /app.
    """
    raw_args = list(config.get("args") or [])
    tail = remote_bridge_tail_args(raw_args)
    # Broker su rete interna in HTTP: mcp-remote rifiuta http:// non loopback senza flag.
    if config.get("allow_http") is True and "--allow-http" not in tail:
        tail.append("--allow-http")

    local = mcp_remote_proxy_path()
    if local:
        return ("node", [local, *tail])
    if shutil.which("npx"):
        return ("npx", ["-y", f"mcp-remote@{MCP_REMOTE_VERSION}", *tail])

    command = str(config.get("command") or "node")
    return (command, raw_args)


def build_remote_bridge_registry_config(
    url: str,
    name: str,
    description: str = "",
    auth_type: str = "oauth2",
    credential_mode: str = "per_user",
) -> Dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_").upper()

    args = [
        "node_modules/mcp-remote/dist/proxy.js",
        url,
    ]
    env: Dict[str, str] = {}
    auth_key = ""

    if auth_type == "oauth2":
        auth_key = "OAUTH_TOKEN"
    elif auth_type == "api-key":
        auth_key = "API_KEY"
    elif auth_type == "basic":
        auth_key = "BASIC_AUTH"

    env_var = f"AION_USER_{slug}__{auth_key}" if auth_key else ""

    if auth_key:
        if credential_mode == "per_user":
            args.extend(
                ["--header", "Authorization: Bearer ${" + env_var + "}"]
                if auth_type != "basic"
                else ["--header", "Authorization: Basic ${" + env_var + "}"]
            )
            env[auth_key] = "${" + env_var + "}"
            env[env_var] = "${" + env_var + "}"
        elif credential_mode == "org_shared":
            args.extend(
                ["--header", "Authorization: Bearer ${" + auth_key + "}"]
                if auth_type != "basic"
                else ["--header", "Authorization: Basic ${" + auth_key + "}"]
            )
            env[auth_key] = "${" + auth_key + "}"
        # auth_type "none" or credential_mode "none": no auth header

    config: Dict[str, Any] = {
        "type": "remote-bridge",
        "command": "node",
        "args": args,
        "env": env,
        "remote_url": url,
        "aion_market_install": "remote",
        "description": description,
    }
    if auth_key and credential_mode == "per_user":
        config["auth_env_var"] = env_var
    elif auth_key and credential_mode == "org_shared":
        # Token unico dell'organizzazione: mcp-remote legge ${API_KEY}, non AION_USER_*.
        config["auth_env_var"] = auth_key
    return config
