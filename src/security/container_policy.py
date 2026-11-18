"""
Container run policy for session sandbox (Podman/Docker).

Builds argv for hardened per-session MCP workers and for the jails of
customer-built MCP servers (run + dependency build, see src/mcp_custom).
"""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # import only for type hints: src.mcp_custom imports this module
    from src.mcp_custom.egress import ResolvedEgress


def _truthy(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes", "on")


def container_name_for_session(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return f"aion-sandbox-{digest}"


def is_docker_runtime(runtime: str = "") -> bool:
    """True when the container CLI is Docker (Docker Desktop, moby) rather than Podman."""
    cand = (runtime or os.environ.get("AION_CONTAINER_RUNTIME") or "").strip()
    return "docker" in Path(cand).stem.lower()


def _selinux_mount_suffix(runtime: str = "", *, shared: bool = False) -> str:
    """SELinux relabel option for a bind mount (Podman on SELinux hosts).

    ``Z`` gives the content a label private to one container: right for a session
    folder used by a single sandbox. ``shared=True`` returns ``z`` (label shared by
    several containers), required for the folders of custom MCP servers: the same
    server folder is mounted by one container per user, and dependency folders are
    shared by every server with the same requirements. With ``Z`` the second
    container would take the access away from the first.
    """
    # Docker on Windows/WSL2 and macOS does not support/need SELinux suffixes.
    if is_docker_runtime(runtime):
        return ""
    if os.environ.get("AION_SANDBOX_CONTAINER_SELINUX", "1").lower() in (
        "1",
        "true",
        "yes",
    ):
        return ",z" if shared else ",Z"
    return ""


def _network_mode(runtime: str = "") -> str:
    custom_net = (os.environ.get("AION_SANDBOX_CONTAINER_NETWORK") or "").strip()
    if custom_net:
        return custom_net
    allow_pip = _truthy("AION_SANDBOX_ALLOW_PACKAGE_INSTALL", "1")
    allow_npm = _truthy("AION_SANDBOX_ALLOW_NPM_INSTALL", "1")
    if allow_pip or allow_npm:
        if is_docker_runtime(runtime):
            return "bridge"
        return "slirp4netns"
    return "none"


def _container_user_args(runtime: str = "") -> List[str]:
    """
    Map the sandbox user onto the host deploy user so session files stay owned by it.

    ``AION_SANDBOX_CONTAINER_USERNS``:
    - ``keep-id`` (default for Podman): container uid/gid == host uid/gid (nested user namespace).
    - ``root``: container root, which rootless Podman already maps to the host user.
    """
    if is_docker_runtime(runtime):
        # Docker Desktop on Windows/macOS maps permissions through the virtualization
        # layer; --userns=keep-id is a Podman-only option that causes Docker to error out.
        mode = (
            (os.environ.get("AION_SANDBOX_CONTAINER_USERNS") or "").strip().lower()
        )
        if mode == "root":
            return ["--user", "0:0"]
        uid = (os.environ.get("AION_SANDBOX_HOST_UID") or "").strip()
        gid = (os.environ.get("AION_SANDBOX_HOST_GID") or "").strip()
        if uid and gid:
            return ["--user", f"{uid}:{gid}"]
        return []

    if not (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip():
        return []
    mode = (
        (os.environ.get("AION_SANDBOX_CONTAINER_USERNS") or "keep-id").strip().lower()
    )
    if mode == "root":
        return ["--user", "0:0"]
    uid = (os.environ.get("AION_SANDBOX_HOST_UID") or "1000").strip()
    gid = (os.environ.get("AION_SANDBOX_HOST_GID") or "1000").strip()
    return ["--userns=keep-id", "--user", f"{uid}:{gid}"]


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
        resolve_host_skills_requirements_mount,
        resolve_host_src_mount,
    )

    name = container_name_for_session(session_id)
    host_path = session_host_path.resolve()
    mount = f"{host_path}:/session:rw{_selinux_mount_suffix(runtime)}"

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
        policy_mount = f"{policy_host}:{SANDBOX_FS_POLICY_CONTAINER_PATH}:ro{_selinux_mount_suffix(runtime)}"
        argv.extend(["-v", policy_mount])

    # Live Python sources: Podman often keeps a stale sandbox image while backend bind-mounts
    # config_std/mcp_servers_std. Overlay host src/ so session_exec/session_venv fixes apply
    # without rebuilding aion/sandbox:latest on every deploy.
    src_host = resolve_host_src_mount(image)
    if src_host is not None:
        src_mount = f"{src_host}:/app/src:ro{_selinux_mount_suffix(runtime)}"
        argv.extend(["-v", src_mount])

    skills_req_host = resolve_host_skills_requirements_mount(image)
    if skills_req_host is not None:
        req_mount = (
            f"{skills_req_host}:/app/requirements-sandbox-skills.txt:ro"
            f"{_selinux_mount_suffix(runtime)}"
        )
        argv.extend(["-v", req_mount])

    argv.extend(
        [
            "--memory",
            memory,
            "--cpus",
            cpus,
            "--pids-limit",
            pids,
            f"--network={_network_mode(runtime)}",
            "--label",
            f"aion.session_id={session_id[:64]}",
            "--label",
            "aion.component=session_sandbox",
        ]
    )

    argv.extend(_container_user_args(runtime))

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


def container_name_for_custom_mcp(
    slug: str, *, user_id: str = "", session_id: str = ""
) -> str:
    """Unique container name for one custom MCP process.

    Slug + hashed user/session make it readable in ``docker ps``; the random suffix
    avoids "name already in use" when a previous container of the same pool key is
    still stopping (``--rm`` removes it only after the process exits).
    """
    parts = ["aion-custom", slug]
    if user_id and user_id not in ("default", "none"):
        parts.append(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:8])
    if session_id:
        parts.append(hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8])
    parts.append(secrets.token_hex(3))
    return "-".join(parts)


# Unprivileged uid/gid for custom servers under Docker: the code is mounted
# read-only and /tmp is a tmpfs, so the process never needs root.
_CUSTOM_MCP_DOCKER_USER = "65534:65534"


# Mount point of the company CA bundle inside custom MCP jails (src/mcp_custom/ca.py).
CUSTOM_MCP_CA_PATH = "/etc/aion/ca-bundle.pem"

# Corporate proxy variables forwarded (by name) to the dependency build when set.
_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")


# Entrypoint of the sandbox image that loads the allowlist rules and drops every
# capability before running the server (docker/sandbox-netjail.sh).
NETJAIL_ENTRYPOINT = "/usr/local/bin/aion-netjail"

# The only capabilities a networked jail starts with, all needed by aion-netjail
# and gone before the server's code runs: NET_ADMIN loads the nftables rules into
# the container's own network namespace (never the host's), SETUID/SETGID switch
# to the unprivileged user, SETPCAP empties the capability bounding set.
_NETJAIL_CAPS = ("NET_ADMIN", "SETUID", "SETGID", "SETPCAP")

# Default uid of the sandbox image (USER sandbox in docker/Dockerfile.sandbox),
# used when no explicit user mapping applies.
_SANDBOX_IMAGE_USER = "10001:10001"


def _custom_mcp_user_args(runtime: str) -> List[str]:
    """Unprivileged user for custom MCP containers (run and dependency build)."""
    user_args = _container_user_args(runtime)
    if not user_args and is_docker_runtime(runtime):
        user_args = ["--user", _CUSTOM_MCP_DOCKER_USER]
    return user_args


def custom_mcp_jail_args(runtime: str, egress: Optional["ResolvedEgress"]) -> Tuple[List[str], List[str]]:
    """Network, user and entrypoint flags of a custom MCP jail.

    Returns ``(flags, command)``: ``flags`` go before the image, ``command`` is the
    program run in the image before ``-u <entrypoint>``.

    - No allowlist (``egress`` None or without rules): ``--network=none`` and the
      unprivileged user, the server runs directly with ``python``.
    - Allowlist: the engine's default network (``bridge`` on Docker, pasta or
      slirp4netns on rootless Podman), started as root *of the container* with only
      ``_NETJAIL_CAPS``; ``aion-netjail`` loads the rules rendered by
      ``egress.render_nft`` (everything not listed is refused), then becomes the
      unprivileged user with no capabilities and runs ``python``. Host names are
      pinned with ``--add-host`` and DNS points to the jail's own loopback, where
      nothing answers: a name outside the list fails at once and DNS cannot carry
      data out.
    """
    from src.mcp_custom.egress import render_nft

    user_args = _custom_mcp_user_args(runtime)
    if egress is None or not egress.rules:
        return ["--network=none", *user_args], ["python"]

    # Target user of aion-netjail: the one the engine would have used directly.
    target = _SANDBOX_IMAGE_USER
    if "--user" in user_args:
        target = user_args[user_args.index("--user") + 1]
    uid, _, gid = target.partition(":")
    # Keep the user-namespace mapping (Podman keep-id) but start as container root.
    flags = [a for a in user_args if a.startswith("--userns")]
    flags += ["--user", "0:0"]
    if is_docker_runtime(runtime):
        flags.append("--network=bridge")
    flags += [f"--cap-add={cap}" for cap in _NETJAIL_CAPS]
    flags += ["--dns", "127.0.0.1"]
    for name, ip in egress.hosts:
        flags += ["--add-host", f"{name}:{ip}"]
    flags += [
        "-e",
        f"AION_JAIL_NFT={render_nft(egress.rules)}",
        "-e",
        f"AION_JAIL_UID={uid}",
        "-e",
        f"AION_JAIL_GID={gid or uid}",
    ]
    return flags, [NETJAIL_ENTRYPOINT, "python"]


def build_custom_mcp_run_argv(
    *,
    runtime: str,
    image: str,
    slug: str,
    host_server_dir: Path,
    entrypoint: str = "server.py",
    env: Optional[Dict[str, str]] = None,
    user_id: str = "",
    session_id: str = "",
    memory: Optional[str] = None,
    cpus: Optional[str] = None,
    pids: Optional[str] = None,
    egress: Optional["ResolvedEgress"] = None,
    host_deps_dir: Optional[Path] = None,
    host_ca_bundle: Optional[Path] = None,
    env_file: Optional[Path] = None,
) -> List[str]:
    """
    Return argv for ``runtime run -i ... image`` to run a customer-built MCP server in its own jail.

    Only the server folder is mounted (read-only, at ``/server``) and, when the server
    declares dependencies, the folder where they were installed (read-only, at
    ``/deps``, on ``PYTHONPATH``); no AION data, no ``.env``, no engine socket. The
    code may do anything inside: there is nothing private to read and nothing it can
    modify outside ``/tmp``. Credentials never appear on a command line visible in
    the host process list: ``env_file`` (private, temporary) carries the server's
    variables, and ``env`` lists only multi-line values passed **by name** (``-e
    KEY``, value in the CLI env; see ``ContainerRuntime.build_custom_mcp_spawn``).
    The jail's own variables (``AION_JAIL_*``) come last so nothing can override them.

    ``egress``: the server's resolved network allowlist (``egress.resolve``); None
    or empty means no network at all (see ``custom_mcp_jail_args``).
    """
    name = container_name_for_custom_mcp(slug, user_id=user_id, session_id=session_id)
    host_dir_str = str(host_server_dir.resolve())

    mem_limit = (memory or os.environ.get("AION_CUSTOM_MCP_MEMORY") or "512m").strip()
    cpus_limit = (cpus or os.environ.get("AION_CUSTOM_MCP_CPUS") or "1.0").strip()
    pids_limit = (pids or os.environ.get("AION_CUSTOM_MCP_PIDS") or "128").strip()

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
        f"{host_dir_str}:/server:ro{_selinux_mount_suffix(runtime, shared=True)}",
    ]
    if host_deps_dir is not None:
        argv.extend(["-v", f"{host_deps_dir.resolve()}:/deps:ro{_selinux_mount_suffix(runtime, shared=True)}"])
    if host_ca_bundle is not None:
        argv.extend(["-v", f"{host_ca_bundle.resolve()}:{CUSTOM_MCP_CA_PATH}:ro{_selinux_mount_suffix(runtime, shared=True)}"])
    jail_flags, command = custom_mcp_jail_args(runtime, egress)
    # Server variables first: Docker/Podman apply --env-file, then -e in order (last
    # wins), so the jail's own -e AION_JAIL_* inside jail_flags always prevail.
    if env_file is not None:
        argv.extend(["--env-file", str(env_file)])
    for key in (env or {}):
        if not key.startswith("AION_JAIL_"):
            argv.extend(["-e", key])
    argv.extend(
        [
            "-w",
            "/server",
            "--memory",
            mem_limit,
            "--cpus",
            cpus_limit,
            "--pids-limit",
            pids_limit,
            *jail_flags,
            "--label",
            f"aion.custom_mcp={slug}",
            "--label",
            "aion.component=custom_mcp",
        ]
    )

    # Entrypoint override (the image's own runs session_sandbox/server.py):
    # python directly, or aion-netjail followed by python for a networked jail.
    argv.extend(["--entrypoint", command[0]])

    argv.append(image)
    argv.extend([*command[1:], "-u", entrypoint])
    return argv


# Interpreter that ships pip in the sandbox image (the /opt/venv runtime has none).
# Same Python version as the runtime, so the wheels it installs are compatible.
_BUILD_PYTHON = "/usr/local/bin/python3"


def _build_network(runtime: str) -> Optional[str]:
    """Network of the dependency build container: outbound access to package indexes.

    Only pip runs with this network, and in wheels-only mode it executes no code
    from the packages. The runtime container of the server follows its own network
    allowlist instead (``custom_mcp_jail_args``).
    Docker: ``bridge``. Podman: None, i.e. the engine's rootless default (``pasta``
    on Podman 5, ``slirp4netns`` before): forcing one fails where it is not installed.
    """
    return "bridge" if is_docker_runtime(runtime) else None


def build_custom_mcp_deps_argv(
    *,
    runtime: str,
    image: str,
    slug: str,
    host_src_dir: Path,
    host_deps_dir: Path,
    requirements_rel: str,
    allow_source_builds: bool = False,
    host_ca_bundle: Optional[Path] = None,
) -> List[str]:
    """
    Return argv that installs a custom server's dependencies into ``/deps``.

    Same jail as the server (no capabilities, unprivileged user, read-only root, no
    AION data): the package code is mounted read-only, only the target folder is
    writable. ``--only-binary=:all:`` installs wheels only, which never runs code of
    the packages; source distributions (``setup.py``) are allowed only with
    ``AION_CUSTOM_MCP_ALLOW_SOURCE_BUILDS=1`` and still build inside this jail.
    """
    tmp_opts = "rw,nosuid,size=1g" if allow_source_builds else "rw,noexec,nosuid,size=1g"
    argv: List[str] = [
        runtime,
        "run",
        "--rm",
        "--name",
        f"aion-custom-build-{slug}-{secrets.token_hex(3)}",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        f"/tmp:{tmp_opts}",
        "-v",
        f"{host_src_dir.resolve()}:/server:ro{_selinux_mount_suffix(runtime, shared=True)}",
        "-v",
        f"{host_deps_dir.resolve()}:/deps:rw{_selinux_mount_suffix(runtime, shared=True)}",
    ]
    if host_ca_bundle is not None:
        # Private package indexes behind the company CA.
        argv.extend(["-v", f"{host_ca_bundle.resolve()}:{CUSTOM_MCP_CA_PATH}:ro{_selinux_mount_suffix(runtime, shared=True)}"])
    argv += [
        "-w",
        "/server",
        # pip resolving and unpacking wheels needs more than a running server.
        "--memory",
        "1g",
        "--cpus",
        (os.environ.get("AION_CUSTOM_MCP_CPUS") or "1.0").strip(),
        "--pids-limit",
        "256",
    ]
    network = _build_network(runtime)
    if network:
        argv.append(f"--network={network}")
    argv += [
        "--label",
        f"aion.custom_mcp={slug}",
        "--label",
        "aion.component=custom_mcp_build",
    ]
    argv.extend(_custom_mcp_user_args(runtime))
    for key, value in (
        ("HOME", "/tmp"),
        ("PIP_NO_CACHE_DIR", "1"),
        ("PIP_DISABLE_PIP_VERSION_CHECK", "1"),
        ("PIP_ROOT_USER_ACTION", "ignore"),
    ):
        argv.extend(["-e", f"{key}={value}"])
    if host_ca_bundle is not None:
        argv.extend(["-e", f"PIP_CERT={CUSTOM_MCP_CA_PATH}", "-e", f"SSL_CERT_FILE={CUSTOM_MCP_CA_PATH}"])
    # Corporate proxy: forwarded by name, the value comes from the CLI environment.
    for key in _PROXY_KEYS:
        if os.environ.get(key):
            argv.extend(["-e", key])
    argv.extend(["--entrypoint", _BUILD_PYTHON, image])
    argv.extend(["-m", "pip", "install", "--no-input", "--target", "/deps"])
    if not allow_source_builds:
        argv.append("--only-binary=:all:")
    argv.extend(["-r", f"/server/{requirements_rel}"])
    return argv
