"""
Container run policy for session sandbox (Podman/Docker).

Builds argv for hardened per-session MCP workers.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def container_name_for_session(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return f"aion-sandbox-{digest}"


def _selinux_mount_suffix() -> str:
    if os.environ.get("AION_SANDBOX_CONTAINER_SELINUX", "1").lower() in (
        "1",
        "true",
        "yes",
    ):
        return ",Z"
    return ""


def _network_mode() -> str:
    allow_pip = _truthy("AION_SANDBOX_ALLOW_PACKAGE_INSTALL", "1")
    allow_npm = _truthy("AION_SANDBOX_ALLOW_NPM_INSTALL", "1")
    if allow_pip or allow_npm:
        return (
            os.environ.get("AION_SANDBOX_CONTAINER_NETWORK") or "slirp4netns"
        ).strip()
    return "none"


def _container_run_user() -> Optional[str]:
    if not (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip():
        return None
    uid = (os.environ.get("AION_SANDBOX_HOST_UID") or "1000").strip()
    gid = (os.environ.get("AION_SANDBOX_HOST_GID") or "1000").strip()
    return f"{uid}:{gid}"


SANDBOX_FS_POLICY_CONTAINER_PATH = "/etc/aion/fs_policy.yaml"


def build_container_run_argv(
    *,
    runtime: str,
    image: str,
    session_id: str,
    session_host_path: Path,
    extra_env: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    Return argv for ``runtime run -i ... image`` (stdio-attached MCP worker).
    """
    from .container_paths import (
        SANDBOX_FS_POLICY_CONTAINER_PATH,
        resolve_fs_policy_host_mount,
    )

    name = container_name_for_session(session_id)
    host_path = session_host_path.resolve()
    mount = f"{host_path}:/session:rw{_selinux_mount_suffix()}"

    memory = (os.environ.get("AION_SANDBOX_CONTAINER_MEMORY") or "512m").strip()
    cpus = (os.environ.get("AION_SANDBOX_CONTAINER_CPUS") or "1.0").strip()
    pids = (os.environ.get("AION_SANDBOX_CONTAINER_PIDS_LIMIT") or "256").strip()

    argv: List[str] = [
        runtime,
        "run",
        "--rm",
        "-i",
        "--init",
        "--name",
        name,
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=256m",
        "-v",
        mount,
    ]

    policy_host = resolve_fs_policy_host_mount()
    if policy_host is not None:
        policy_mount = f"{policy_host}:{SANDBOX_FS_POLICY_CONTAINER_PATH}:ro{_selinux_mount_suffix()}"
        argv.extend(["-v", policy_mount])

    argv.extend(
        [
            "--memory",
            memory,
            "--cpus",
            cpus,
            "--pids-limit",
            pids,
            f"--network={_network_mode()}",
            "--label",
            f"aion.session_id={session_id[:64]}",
            "--label",
            "aion.component=session_sandbox",
        ]
    )

    run_user = _container_run_user()
    if run_user:
        argv.extend(["--userns=keep-id", "--user", run_user])

    env = {
        "AION_CHAT_SESSION_ID": session_id,
        "AION_DATA_DIR": "/session",
        "AION_SANDBOX_IN_CONTAINER": "1",
        "AION_SANDBOX_FLAT_SESSION_ROOT": "1",
        "PYTHONUNBUFFERED": "1",
        "NO_COLOR": "1",
        "RUFF_CACHE_DIR": "/tmp/ruff_cache",
    }
    if policy_host is not None:
        env["AION_FS_POLICY_PATH"] = SANDBOX_FS_POLICY_CONTAINER_PATH
    if extra_env:
        for key, val in extra_env.items():
            if key.startswith("AION_CURRENT_"):
                env[key] = val

    for key, val in env.items():
        argv.extend(["-e", f"{key}={val}"])

    argv.append(image)
    return argv


def build_container_stop_argv(*, runtime: str, container_name: str) -> List[str]:
    return [runtime, "stop", "-t", "5", container_name]
