"""
Podman/Docker container runtime for session sandbox MCP workers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .container_policy import (
    build_container_run_argv,
    build_container_stop_argv,
    container_name_for_session,
)

logger = logging.getLogger("aion.security")

_RUNTIME: Optional["ContainerRuntime"] = None


def sandbox_container_mode_enabled() -> bool:
    backend = (os.environ.get("AION_SANDBOX_BACKEND") or "subprocess").strip().lower()
    if backend != "container":
        return False
    if os.environ.get("AION_SANDBOX_MCP_JAIL", "1").lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return False
    return True


def resolve_session_host_mount_path(session_path: Path) -> Path:
    """
    Map container session paths to host paths when Podman/Docker runs on the host
    (e.g. backend in Compose with a mounted Podman socket).
    """
    host_root = (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip()
    if not host_root:
        return session_path.resolve()

    container_data = (os.environ.get("AION_DATA_DIR") or "/app/data").strip()
    resolved = session_path.resolve()
    container_base = Path(container_data).resolve()
    try:
        rel = resolved.relative_to(container_base)
    except ValueError:
        return resolved
    return (Path(host_root).resolve() / rel).resolve()


def prepare_session_host_mount(session_path: Path) -> None:
    """
    Ensure bind-mounted session dirs are writable by the sandbox container user.

    The backend (often root in Docker) creates ``uploads/``, ``workspace/``, etc.
    Rootless Podman runs the sandbox as the host deploy user (default uid 1000).

    Only touches the session root and standard subdirs — never follows ``.venv/``
    symlinks (which may point at the host/backend Python and must not be chmodded).
    """
    if not (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip():
        return

    uid = int((os.environ.get("AION_SANDBOX_HOST_UID") or "1000").strip())
    gid = int((os.environ.get("AION_SANDBOX_HOST_GID") or "1000").strip())
    root = session_path.resolve()

    def _fix_dir(path: Path) -> None:
        if not path.is_dir():
            return
        try:
            os.chown(path, uid, gid)
            path.chmod(0o775)
        except OSError as exc:
            logger.warning("session_mount_chown failed path=%s: %s", path, exc)

    _fix_dir(root)
    for name in ("uploads", "derived", "workspace"):
        _fix_dir(root / name)


class ContainerRuntime:
    def __init__(self) -> None:
        self.runtime = (
            (os.environ.get("AION_CONTAINER_RUNTIME") or "podman").strip().lower()
        )
        self.image = (
            os.environ.get("AION_SANDBOX_CONTAINER_IMAGE") or "aion/sandbox:latest"
        ).strip()
        self.socket = (os.environ.get("AION_PODMAN_SOCKET") or "").strip()

    def _base_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        if self.socket:
            env["CONTAINER_HOST"] = f"unix://{self.socket}"
        return env

    def is_available(self) -> bool:
        exe = shutil.which(self.runtime)
        if not exe:
            return False
        try:
            proc = subprocess.run(
                [exe, "info"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._base_env(),
            )
            return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def container_name_for_session(self, session_id: str) -> str:
        return container_name_for_session(session_id)

    def build_stdio_spawn(
        self,
        session_id: str,
        *,
        profile_slug: str = "",
        user_id: str = "",
        tenant_id: str = "",
    ) -> Tuple[str, List[str], Dict[str, str]]:
        """
        Return (command, args, env) for MCP stdio_client when using container jail.
        """
        from ..session_workspace import ensure_session_dirs, session_root

        ensure_session_dirs(session_id)
        session_path = session_root(session_id)
        prepare_session_host_mount(session_path)
        host_session = resolve_session_host_mount_path(session_path)
        audit_env: Dict[str, str] = {}
        if profile_slug:
            audit_env["AION_CURRENT_PROFILE_SLUG"] = profile_slug
        if user_id:
            audit_env["AION_CURRENT_USER_ID"] = user_id
        if tenant_id:
            audit_env["AION_CURRENT_TENANT_ID"] = tenant_id

        argv = build_container_run_argv(
            runtime=self.runtime,
            image=self.image,
            session_id=session_id,
            session_host_path=host_session,
            extra_env=audit_env,
        )
        command = argv[0]
        args = argv[1:]
        spawn_env = self._base_env()
        logger.info(
            "sandbox_container_start session=%s runtime=%s image=%s name=%s mount=%s",
            session_id[:8],
            self.runtime,
            self.image,
            container_name_for_session(session_id),
            host_session,
        )
        return command, args, spawn_env

    async def stop_session_container(self, session_id: str) -> None:
        name = container_name_for_session(session_id)
        argv = build_container_stop_argv(runtime=self.runtime, container_name=name)
        env = self._base_env()

        def _stop() -> None:
            try:
                subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=env,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning(
                    "sandbox_container_stop failed session=%s: %s", session_id[:8], exc
                )

        await asyncio.to_thread(_stop)
        logger.info("sandbox_container_stop session=%s name=%s", session_id[:8], name)


def get_container_runtime() -> ContainerRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = ContainerRuntime()
    return _RUNTIME
