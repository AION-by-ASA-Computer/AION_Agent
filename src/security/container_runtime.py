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


# ── Environment of custom MCP jails ──────────────────────────────────────────
# The server's variables (manifest env, admin edits, credentials) must reach the
# container WITHOUT becoming the environment of the docker/podman CLI process: the
# CLI reads its own configuration from env (DOCKER_HOST, HTTPS_PROXY, HOME, ...), so a
# manifest declaring DOCKER_HOST=tcp://attacker would redirect the CLI, and every
# credential, to another daemon. They travel in a temporary --env-file instead.

# Variables the container CLIs read for themselves (Docker/Podman are Go programs).
# Only relevant to the rare multi-line values, which --env-file cannot carry and are
# still passed by name through the CLI env: for these names they are dropped.
_CLI_ENV_EXACT = frozenset(
    {
        "PATH", "HOME", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "REGISTRY_AUTH_FILE",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    }
)
_CLI_ENV_PREFIXES = ("DOCKER_", "CONTAINER_", "CONTAINERS_", "PODMAN_", "BUILDAH_", "BUILDKIT_", "GO", "XDG_", "LD_")

# Seconds an env file is kept: the CLI reads it when it starts (milliseconds), the
# margin covers a slow engine. Files left by a crash are removed at the next write.
_ENV_FILE_TTL_SECONDS = 60


def _cli_reads(key: str) -> bool:
    """True when the docker/podman CLI would interpret ``key`` as its own setting."""
    return key in _CLI_ENV_EXACT or key.startswith(_CLI_ENV_PREFIXES)


def _env_file_dir() -> Path:
    """Private folder (0700) for the jails' env files, in the backend's temp dir."""
    import tempfile

    folder = Path(tempfile.gettempdir()) / "aion-custom-mcp-env"
    folder.mkdir(mode=0o700, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    return folder


def _remove_later(path: Path, delay: float = _ENV_FILE_TTL_SECONDS) -> None:
    """Delete ``path`` after ``delay`` seconds (background timer, never raises)."""
    import threading

    timer = threading.Timer(delay, lambda: path.unlink(missing_ok=True))
    timer.daemon = True
    timer.start()


def write_jail_env_file(slug: str, env: Dict[str, str]) -> Tuple[Optional[Path], Dict[str, str]]:
    """Split a jail's env into an --env-file and the few values passed by name.

    Returns ``(env_file, by_name)``:
    - ``env_file``: private temporary file (0600) with every single-line value,
      deleted shortly after (the CLI reads it at start); None when empty;
    - ``by_name``: multi-line values (e.g. a PEM key), which ``--env-file`` cannot
      carry: passed as ``-e KEY`` with the value in the CLI env, as before. Names
      the CLI reads for itself are dropped (logged) so they cannot steer it.
    Side effects: writes the file; removes env files older than the TTL.
    """
    import tempfile
    import time

    folder = _env_file_dir()
    now = time.time()
    for old in folder.glob("*.env"):
        try:
            if now - old.stat().st_mtime > _ENV_FILE_TTL_SECONDS * 2:
                old.unlink(missing_ok=True)
        except OSError:
            pass

    single: Dict[str, str] = {}
    by_name: Dict[str, str] = {}
    for key, value in env.items():
        text = str(value)
        if "\n" in text or "\r" in text or "\0" in text:
            if _cli_reads(key):
                logger.warning("custom_mcp_env slug=%s multi-line value of %s dropped (container CLI setting)", slug, key)
                continue
            by_name[key] = text
        else:
            single[key] = text
    if not single:
        return None, by_name

    fd, name = tempfile.mkstemp(prefix=f"{slug}-", suffix=".env", dir=folder)  # created 0600
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        for key, value in single.items():
            fh.write(f"{key}={value}\n")
    path = Path(name)
    _remove_later(path)
    return path, by_name

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


def _resolve_container_socket() -> str:
    """Pick a Podman/Docker socket path that exists inside the current process namespace."""
    explicit = (
        os.environ.get("AION_PODMAN_SOCKET")
        or os.environ.get("AION_DOCKER_SOCKET")
        or ""
    ).strip()
    container_host = (
        os.environ.get("CONTAINER_HOST")
        or os.environ.get("DOCKER_HOST")
        or ""
    ).strip()
    if container_host.startswith("unix://"):
        container_host = container_host[len("unix://") :]
    for candidate in (explicit, container_host):
        if candidate and Path(candidate).exists():
            return candidate
    return explicit or container_host


def resolve_custom_mcp_host_path(server_path: Path) -> Path:
    """
    Map a path under ``mcp_servers/custom`` to the path the container engine sees.

    The engine (host Podman/Docker reached through the socket) resolves bind-mount
    sources on the host, not inside the backend container. Standard layout: derived
    from the deployment folder, i.e. the parent of ``AION_SANDBOX_HOST_DATA_DIR`` (or
    ``AION_SANDBOX_HOST_REPO``), the variable the session sandbox already requires,
    so custom MCP servers need no extra setting. ``AION_CUSTOM_MCP_HOST_DIR`` is only
    an override for deployments where ``mcp_servers/custom`` lives elsewhere. With
    the backend running directly on the host the path is used as is.
    """
    explicit = (os.environ.get("AION_CUSTOM_MCP_HOST_DIR") or "").strip()
    resolved = server_path.resolve()
    if explicit:
        # Any path under mcp_servers/custom (server folder, staged upload, installed
        # dependencies) keeps its relative position under the host folder.
        from ..mcp_custom.paths import custom_root

        try:
            rel = resolved.relative_to(custom_root().resolve())
        except ValueError:
            rel = Path(resolved.name)
        return Path(explicit) / rel

    from .container_paths import resolve_host_repo_root

    host_repo = resolve_host_repo_root()
    if host_repo is not None:
        container_app = Path("/app").resolve()
        try:
            rel = resolved.relative_to(container_app)
            return (host_repo / rel).resolve()
        except ValueError:
            pass
    return resolved


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
    for name in ("uploads", "derived", "workspace", ".npm", ".venv"):
        _fix_dir(root / name)

    npm_dir = root / ".npm"
    if npm_dir.is_dir():
        for dirpath, _, filenames in os.walk(npm_dir):
            _fix_dir(Path(dirpath))
            for f in filenames:
                try:
                    fpath = Path(dirpath) / f
                    os.chown(fpath, uid, gid)
                    fpath.chmod(0o664)
                except OSError:
                    pass


class ContainerRuntime:
    def __init__(self) -> None:
        configured = (os.environ.get("AION_CONTAINER_RUNTIME") or "").strip().lower()
        if configured:
            self.runtime = configured
        else:
            # Auto-detect: if docker is available and podman is not, default to docker
            if shutil.which("docker") and not shutil.which("podman"):
                self.runtime = "docker"
            else:
                self.runtime = "podman"
        self.image = (
            os.environ.get("AION_SANDBOX_CONTAINER_IMAGE") or "aion/sandbox:latest"
        ).strip()
        self.socket = _resolve_container_socket()

    def _base_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        if self.socket:
            if "docker" in self.runtime:
                if "DOCKER_HOST" not in env:
                    socket_uri = (
                        self.socket
                        if self.socket.startswith(("unix://", "npipe://", "tcp://"))
                        else f"unix://{self.socket}"
                    )
                    env["DOCKER_HOST"] = socket_uri
            else:
                if "CONTAINER_HOST" not in env:
                    socket_uri = (
                        self.socket
                        if self.socket.startswith(("unix://", "tcp://"))
                        else f"unix://{self.socket}"
                    )
                    env["CONTAINER_HOST"] = socket_uri
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

    def build_custom_mcp_spawn(
        self,
        slug: str,
        *,
        server_path: Path,
        entrypoint: str = "server.py",
        env: Optional[Dict[str, str]] = None,
        user_id: str = "",
        session_id: str = "",
        deps_path: Optional[Path] = None,
        network_allow: Optional[List[str]] = None,
        ca_path: Optional[Path] = None,
    ) -> Tuple[str, List[str], Dict[str, str]]:
        """
        Return (command, args, env) to spawn a customer-built MCP server in its own jail.

        ``deps_path``: folder with the server's installed dependencies (mounted
        read-only at ``/deps``); None when the server declares none.
        ``network_allow``: validated allowlist (``mcp_custom.egress``); empty or
        None means no network. Host names are resolved here, at every start, so a
        restart of the server picks up changed addresses.
        ``ca_path``: combined CA bundle (src/mcp_custom/ca.py), mounted read-only.
        """
        from src.mcp_custom.egress import parse_allowlist, resolve

        from .container_policy import build_custom_mcp_run_argv

        egress = resolve(parse_allowlist(network_allow)) if network_allow else None
        for warning in egress.warnings if egress else []:
            logger.warning("custom_mcp_network slug=%s %s", slug, warning)
        host_dir = resolve_custom_mcp_host_path(server_path)
        # Server variables -> private --env-file (never the CLI's own environment);
        # only multi-line values still go by name (see write_jail_env_file).
        env_file, by_name = write_jail_env_file(slug, {k: str(v) for k, v in (env or {}).items()})
        argv = build_custom_mcp_run_argv(
            runtime=self.runtime,
            image=self.image,
            slug=slug,
            host_server_dir=host_dir,
            entrypoint=entrypoint,
            env=by_name,
            env_file=env_file,
            user_id=user_id,
            session_id=session_id,
            host_deps_dir=resolve_custom_mcp_host_path(deps_path) if deps_path else None,
            egress=egress,
            host_ca_bundle=resolve_custom_mcp_host_path(ca_path) if ca_path else None,
        )
        command = argv[0]
        args = argv[1:]
        # The CLI runs with the backend's own environment plus, only for multi-line
        # values, the variables listed by name (-e KEY) in the argv: names the CLI
        # reads for itself were already dropped, so nothing here can steer it.
        spawn_env = self._base_env()
        spawn_env.update(by_name)
        logger.info(
            "custom_mcp_container_start slug=%s runtime=%s image=%s mount=%s",
            slug,
            self.runtime,
            self.image,
            host_dir,
        )
        return command, args, spawn_env

    def build_custom_mcp_deps_command(
        self,
        slug: str,
        *,
        src_path: Path,
        deps_path: Path,
        requirements_rel: str,
        allow_source_builds: bool = False,
        ca_path: Optional[Path] = None,
    ) -> Tuple[List[str], Dict[str, str]]:
        """argv + env of the container that installs a custom server's dependencies."""
        from .container_policy import build_custom_mcp_deps_argv

        argv = build_custom_mcp_deps_argv(
            runtime=self.runtime,
            image=self.image,
            slug=slug,
            host_src_dir=resolve_custom_mcp_host_path(src_path),
            host_deps_dir=resolve_custom_mcp_host_path(deps_path),
            requirements_rel=requirements_rel,
            allow_source_builds=allow_source_builds,
            host_ca_bundle=resolve_custom_mcp_host_path(ca_path) if ca_path else None,
        )
        return argv, self._base_env()

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

    def remove_custom_mcp_containers(self, slug: str) -> int:
        """Force-remove every container of a custom MCP server (label ``aion.custom_mcp``).

        Called when the server is deleted: pooled workers are stopped first, this
        catches containers left behind (backend restart, crashed worker). Returns the
        number of containers removed; failures are logged, never raised.
        """
        env = self._base_env()
        try:
            listed = subprocess.run(
                [self.runtime, "ps", "-aq", "--filter", f"label=aion.custom_mcp={slug}"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            ids = [i for i in listed.stdout.split() if i.strip()]
            if ids:
                subprocess.run(
                    [self.runtime, "rm", "-f", *ids],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
            return len(ids)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("custom_mcp_container_cleanup failed slug=%s: %s", slug, exc)
            return 0


def get_container_runtime() -> ContainerRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = ContainerRuntime()
    return _RUNTIME
