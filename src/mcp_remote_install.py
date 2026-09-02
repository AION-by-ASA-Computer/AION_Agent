"""Remote MCP bridge registry helpers (mcp-remote stdio proxy)."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    ``npx -y mcp-remote`` when the package is not installed under /app.
    """
    raw_args = list(config.get("args") or [])
    tail = remote_bridge_tail_args(raw_args)

    local = mcp_remote_proxy_path()
    if local:
        return ("node", [local, *tail])
    if shutil.which("npx"):
        return ("npx", ["-y", "mcp-remote", *tail])

    command = str(config.get("command") or "node")
    return (command, raw_args)


def build_remote_bridge_registry_config(
    url: str,
    name: str,
    description: str = "",
    auth_type: str = "oauth2",
) -> Dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_").upper()

    args = [
        "node_modules/mcp-remote/dist/proxy.js",
        url,
    ]
    env: Dict[str, str] = {}

    if auth_type == "oauth2":
        env_var = f"AION_USER_{slug}__OAUTH_TOKEN"
        args.extend(["--header", "Authorization: Bearer ${" + env_var + "}"])
        env[env_var] = "${" + env_var + "}"
    elif auth_type == "api-key":
        env_var = f"AION_USER_{slug}__API_KEY"
        args.extend(["--header", "Authorization: Bearer ${" + env_var + "}"])
        env[env_var] = "${" + env_var + "}"
    elif auth_type == "basic":
        env_var = f"AION_USER_{slug}__BASIC_AUTH"
        args.extend(["--header", "Authorization: Basic ${" + env_var + "}"])
        env[env_var] = "${" + env_var + "}"
    # auth_type "none": no Authorization header

    config: Dict[str, Any] = {
        "type": "remote-bridge",
        "command": "node",
        "args": args,
        "env": env,
        "remote_url": url,
        "aion_market_install": "remote",
        "description": description,
    }
    if auth_type != "none":
        config["auth_env_var"] = env_var
    return config
