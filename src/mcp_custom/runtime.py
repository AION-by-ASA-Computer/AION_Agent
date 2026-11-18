"""Spawn policy applied to every customer-built MCP server process.

Called by both stdio spawn sites of ``src/mcp_manager.py`` (pooled worker and
one-shot session) right before ``StdioServerParameters`` is built. For servers
that are not custom it returns the inputs unchanged.

For custom servers it enforces, whatever the registry says:

- **kill switch**: ``AION_CUSTOM_MCP_FORCE_DISABLE=1`` refuses every start;
- **isolation requirement**: custom servers must run in their own container. The
  container runner is the next step of the plan (Fase 1.5); until then a custom
  server starts only with ``AION_CUSTOM_MCP_ALLOW_UNSANDBOXED=1`` (development);
- **command**: the runtime interpreter + the entrypoint recorded at activation,
  never ``command``/``args`` from the registry (an edit cannot point elsewhere);
- **environment rebuilt from scratch**: the third-party allowlist (no AION
  secrets, no ``PYTHONPATH`` to AION's code), AION context variables, the
  manifest's literal ``env`` and the server's own credentials;
- **credentials only from the encrypted store**: ``${VAR}`` placeholders are
  never expanded from the backend environment for custom servers, so a manifest
  declaring e.g. ``OPENAI_API_KEY`` cannot receive AION's own key;
- **working directory**: the server folder (relative paths in the code work).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import settings
from .integration import custom_credential_mode, custom_credential_schema, custom_meta
from .manifest import env_key_error
from .paths import is_custom_config, server_dir

logger = logging.getLogger("aion.mcp_custom.runtime")

# Variables copied from the env the spawn pipeline already prepared: AION context
# for the server (who is asking, from which profile/session) and the per-user HOME
# isolation. Nothing else from that env reaches a custom server.
_CONTEXT_KEYS = (
    "AION_CURRENT_PROFILE_SLUG",
    "AION_CURRENT_USER_ID",
    "AION_CURRENT_TENANT_ID",
    "AION_CHAT_SESSION_ID",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
)

# Quiet, deterministic interpreter/FastMCP behaviour (stdout is the MCP channel).
_FIXED_ENV = {
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONIOENCODING": "utf-8",
    "FASTMCP_LOG_LEVEL": "WARNING",
    "FASTMCP_SHOW_SERVER_BANNER": "false",
    "FASTMCP_CHECK_FOR_UPDATES": "off",
    "NO_COLOR": "1",
}


class CustomMcpUnavailable(RuntimeError):
    """A custom server may not start (kill switch, missing isolation, missing code)."""


# `docker info` / `podman info` takes up to seconds and runs synchronously: cache the
# answer so starting a custom server does not block the event loop on every spawn.
_RUNTIME_CHECK_TTL_SECONDS = 60.0
_runtime_check: Dict[str, Any] = {"at": 0.0, "ok": False}


def container_isolation_available() -> bool:
    """True when the container engine answers (cached for a minute)."""
    import time

    now = time.monotonic()
    if now - _runtime_check["at"] < _RUNTIME_CHECK_TTL_SECONDS:
        return bool(_runtime_check["ok"])
    from ..security.container_runtime import get_container_runtime

    ok = bool(get_container_runtime().is_available())
    _runtime_check.update(at=now, ok=ok)
    return ok


def ensure_can_start(server_name: str, config: Optional[Dict[str, Any]]) -> None:
    """Raise ``CustomMcpUnavailable`` when a custom server must not be started.

    Isolation rule: a custom server always runs in its own container when the
    engine is available. ``AION_CUSTOM_MCP_ALLOW_UNSANDBOXED=1`` is only a fallback
    for machines without a container engine; it never disables a working jail.
    """
    if not is_custom_config(config):
        return
    if settings.force_disabled():
        raise CustomMcpUnavailable(
            f"custom MCP '{server_name}' not started: AION_CUSTOM_MCP_FORCE_DISABLE=1"
        )
    if not container_isolation_available() and not settings.allow_unsandboxed():
        from ..security.container_runtime import get_container_runtime

        raise CustomMcpUnavailable(
            f"custom MCP '{server_name}' requires container isolation, but container runtime "
            f"'{get_container_runtime().runtime}' is not available. Start Docker/Podman, "
            "or set AION_CUSTOM_MCP_ALLOW_UNSANDBOXED=1 for local development only."
        )


def _entrypoint_path(server_name: str, config: Dict[str, Any]) -> Path:
    """Absolute entrypoint inside the server folder (checked to stay inside it)."""
    meta = custom_meta(config) or {}
    folder = server_dir(server_name).resolve()
    entry = (folder / str(meta.get("entrypoint") or "server.py")).resolve()
    if folder not in entry.parents or not entry.is_file():
        raise CustomMcpUnavailable(
            f"custom MCP '{server_name}' not started: entrypoint missing in mcp_servers/custom/{server_name}/"
        )
    return entry


def _literal_env(
    server_name: str, credential_keys: set, config: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """Non-secret ``env`` values of the registry entry, placeholders excluded.

    Read from the raw (unresolved) registry: the config passed to the spawn code
    comes from ``get_server_config``, which already expanded ``${VAR}`` from the
    backend environment.
    """
    from ..mcp_manager import mcp_manager

    reg_entry = (
        mcp_manager._registry.get(server_name)
        if hasattr(mcp_manager, "_registry")
        else None
    )
    raw = (reg_entry or config or {}).get("env")
    env_block = raw if isinstance(raw, dict) else {}
    out: Dict[str, str] = {}
    for key, value in env_block.items():
        if key in credential_keys:
            continue
        # Same name rules as the manifest, also for admin edits and hand-edited
        # registries: reserved names (PATH, LD_*, PYTHON*, AION_*...) never reach the jail.
        err = env_key_error(str(key))
        if err:
            logger.warning(
                "Custom MCP '%s': env %s ignored (%s)", server_name, key, err
            )
            continue
        if isinstance(value, str) and "${" not in value:
            out[str(key)] = value
    return out


async def _credential_env(
    server_name: str, config: Dict[str, Any], user_id: str, tenant_id: str
) -> Dict[str, str]:
    """Credential values for this server, read only from the encrypted store.

    ``get_credential`` applies the server's mode: ``per_user`` reads only the
    current user's values, ``org_shared`` the user's override then the shared one.
    Missing values are simply absent: the server sees an unset variable.
    """
    from ..runtime.credential_store import get_credential

    out: Dict[str, str] = {}
    if custom_credential_mode(config) in (None, "none"):
        return out
    for field in custom_credential_schema(config) or []:
        key = str(field.get("key") or "")
        if not key or env_key_error(key):
            continue
        value = await get_credential(
            user_id or "default", server_name, key, tenant_id=tenant_id or "default"
        )
        if value is not None and str(value) != "":
            out[key] = str(value)
    return out


def base_process_env() -> Dict[str, str]:
    """Starting env of every custom server process (run and verification probe).

    The third-party allowlist (no AION secrets, ignoring the AION_MCP_ENV_SCRUB
    emergency switch) plus fixed interpreter settings; container-engine addresses
    removed (a customer's server has no reason to know where the engine is).
    """
    from ..security.session_env import build_mcp_stdio_base_env

    env: Dict[str, str] = dict(
        build_mcp_stdio_base_env(first_party=False, always_scrub=True)
    )
    for key in ("DOCKER_HOST", "CONTAINER_HOST"):
        env.pop(key, None)
    env.update(_FIXED_ENV)
    return env


def network_allowlist(
    config: Optional[Dict[str, Any]], manifest_list: Optional[List[str]] = None
) -> List[str]:
    """Network allowlist of a custom server (empty list = no network).

    Registry value (set at activation from the manifest, editable by the admin
    from the MCP Hub), else ``manifest_list`` (verification of a staged upload).
    Entries are re-validated here: an invalid list (e.g. a hand-edited registry)
    fails closed to "no network" instead of starting with unchecked rules.
    """
    from .egress import AllowlistError, normalize_allowlist

    value = (
        (custom_meta(config) or {}).get("network")
        if config is not None
        else manifest_list
    )
    if not isinstance(value, list):
        return []
    try:
        return normalize_allowlist(value)
    except AllowlistError as exc:
        logger.warning("Custom MCP network allowlist ignored (no network): %s", exc)
        return []


def finalize_process_env(
    env: Dict[str, str],
    *,
    in_container: bool,
    deps_dir: Optional[Path],
    ca_path: Optional[Path] = None,
) -> Dict[str, str]:
    """Paths the process needs, depending on where it runs.

    In the jail the root filesystem is read-only: HOME and caches go to the /tmp
    tmpfs (the backend's per-user HOME does not exist there) and the installed
    dependencies are on PYTHONPATH from their read-only mount at /deps. With a
    company CA configured, the TLS variables point to the combined bundle (mounted
    at /etc/aion/ca-bundle.pem). On the host fallback the folders are used in place.
    """
    from .ca import CA_IN_CONTAINER, ca_env

    out = dict(env)
    if ca_path is not None:
        out.update(ca_env(CA_IN_CONTAINER if in_container else str(ca_path.resolve())))
    if in_container:
        # PATH comes from the image (the backend's may even be a Windows PATH);
        # the netjail entrypoint and python are found through it.
        for key in (
            "PATH",
            "USERPROFILE",
            "APPDATA",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
        ):
            out.pop(key, None)
        out["HOME"] = "/tmp"
        out["XDG_CACHE_HOME"] = "/tmp/.cache"
        if deps_dir is not None:
            out["PYTHONPATH"] = "/deps"
    elif deps_dir is not None:
        out["PYTHONPATH"] = str(deps_dir.resolve())
    return out


def installed_deps_dir(server_name: str, config: Dict[str, Any]) -> Optional[Path]:
    """Dependency folder recorded at activation, or None when the server has none.

    Raises ``CustomMcpUnavailable`` when the folder was recorded but is gone (the
    server would fail on its imports): uploading the package again rebuilds it.
    """
    from .verify import deps_ready, deps_path

    key = str((custom_meta(config) or {}).get("deps_key") or "")
    if not key:
        return None
    if not deps_ready(key):
        raise CustomMcpUnavailable(
            f"custom MCP '{server_name}' not started: its installed dependencies are missing; upload the package again"
        )
    return deps_path(key)


async def prepare_custom_spawn(
    server_name: str,
    config: Dict[str, Any],
    command: str,
    args: List[str],
    env: Dict[str, Any],
    *,
    user_id: str,
    tenant_id: str,
) -> Tuple[str, List[str], Dict[str, str], Optional[str]]:
    """Return ``(command, args, env, cwd)`` to spawn ``server_name``.

    Non-custom servers: inputs returned unchanged and ``cwd`` None. Custom
    servers: see the module docstring. Raises ``CustomMcpUnavailable``.
    """
    if not is_custom_config(config):
        return command, args, env, None
    ensure_can_start(server_name, config)
    entry = _entrypoint_path(server_name, config)
    deps_dir = installed_deps_dir(server_name, config)
    from .ca import jail_ca_bundle

    ca_path = jail_ca_bundle()

    credential_keys = {
        str(f.get("key")) for f in custom_credential_schema(config) or []
    }
    new_env = base_process_env()
    for key in _CONTEXT_KEYS:
        if env.get(key):
            new_env[key] = str(env[key])
    new_env.update(_literal_env(server_name, credential_keys, config))
    new_env.update(await _credential_env(server_name, config, user_id, tenant_id))

    # Fallback only (ensure_can_start allowed it): no container engine on this machine
    # and the development flag is set. The process shares the backend's filesystem.
    if not container_isolation_available():
        logger.warning(
            "Custom MCP '%s' running WITHOUT container isolation: no container engine "
            "available and AION_CUSTOM_MCP_ALLOW_UNSANDBOXED=1 (development only)",
            server_name,
        )
        host_env = finalize_process_env(
            new_env, in_container=False, deps_dir=deps_dir, ca_path=ca_path
        )
        return (
            sys.executable,
            ["-u", str(entry)],
            host_env,
            str(server_dir(server_name).resolve()),
        )

    # Default: hardened container jail (one container per server and user).
    from ..security.container_runtime import get_container_runtime

    container_runtime = get_container_runtime()
    meta = custom_meta(config) or {}
    entrypoint_rel = str(meta.get("entrypoint") or "server.py")
    session_id = str(env.get("AION_CHAT_SESSION_ID") or "")

    cmd, c_args, spawn_env = container_runtime.build_custom_mcp_spawn(
        server_name,
        server_path=server_dir(server_name),
        entrypoint=entrypoint_rel,
        env=finalize_process_env(
            new_env, in_container=True, deps_dir=deps_dir, ca_path=ca_path
        ),
        user_id=user_id,
        session_id=session_id,
        deps_path=deps_dir,
        network_allow=network_allowlist(config),
        ca_path=ca_path,
    )
    return cmd, c_args, spawn_env, None
