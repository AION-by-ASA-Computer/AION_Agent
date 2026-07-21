"""Host/container path mapping for session sandbox sidecars."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

SANDBOX_FS_POLICY_CONTAINER_PATH = "/etc/aion/fs_policy.yaml"


def resolve_host_repo_root() -> Optional[Path]:
    """
    Host checkout root for bind-mounting live ``src/`` into Podman sandboxes.

    Derived from ``AION_SANDBOX_HOST_REPO`` or parent of ``AION_SANDBOX_HOST_DATA_DIR``.
    Paths are for the **host** Podman daemon — do not require them to exist inside the
    backend container filesystem.
    """
    explicit = (os.environ.get("AION_SANDBOX_HOST_REPO") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    host_data = (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip()
    if not host_data:
        return None
    return Path(host_data).expanduser().resolve().parent


def resolve_host_src_mount() -> Optional[Path]:
    """Host ``src/`` directory to overlay ``/app/src`` in session sandbox containers."""
    root = resolve_host_repo_root()
    if root is None:
        return None
    return (root / "src").resolve()


def resolve_host_skills_requirements_mount() -> Optional[Path]:
    """Host ``requirements-sandbox-skills.txt`` for session venv bootstrap in sandboxes."""
    root = resolve_host_repo_root()
    if root is None:
        return None
    return (root / "requirements-sandbox-skills.txt").resolve()


def resolve_host_repo_path(container_path: Path) -> Path:
    """
    Map a path under the backend repo (e.g. ``/app/config/...``) to the host
    checkout when ``AION_SANDBOX_HOST_DATA_DIR`` points at ``<repo>/data``.
    """
    host_data = (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip()
    resolved = container_path.resolve()
    if not host_data:
        return resolved

    container_data = Path(os.environ.get("AION_DATA_DIR") or "/app/data").resolve()
    container_repo = container_data.parent
    try:
        rel = resolved.relative_to(container_repo)
    except ValueError:
        return resolved
    host_repo = Path(host_data).resolve().parent
    return (host_repo / rel).resolve()


def resolve_fs_policy_host_mount() -> Optional[Path]:
    """
    Host path to bind-mount into the session sandbox container as the active
    filesystem/exec policy (``AION_FS_POLICY_PATH``).
    """
    path_env = (os.environ.get("AION_FS_POLICY_PATH") or "").strip()
    if not path_env:
        return None

    policy = Path(path_env).expanduser()
    if not policy.is_absolute():
        container_data = Path(os.environ.get("AION_DATA_DIR") or "/app/data").resolve()
        policy = (container_data.parent / policy).resolve()
    else:
        policy = policy.resolve()

    if not policy.is_file():
        return None

    host_policy = resolve_host_repo_path(policy)
    host_data = (os.environ.get("AION_SANDBOX_HOST_DATA_DIR") or "").strip()
    if host_data:
        # Path is for Podman on the host; it is often not visible inside the
        # backend container (only ``/app/config`` is bind-mounted there).
        return host_policy
    if host_policy.is_file():
        return host_policy
    return None
