"""Remote MCP bridge registry helpers (mcp-remote stdio proxy)."""

from __future__ import annotations

import re
from typing import Any, Dict


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
        # We DO NOT pass --header for oauth2 anymore. 
        # AION will pre-seed the mcp-remote cache and mcp-remote will use it.
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
