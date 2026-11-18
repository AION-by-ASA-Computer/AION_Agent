"""Activation, listing and removal of customer-built MCP servers.

``activate`` turns a reviewed upload (``package.StagedUpload`` with status
``ready``) into a live MCP server:

1. the previous version (if any) is archived under ``.versions/<slug>/`` and the
   staged code is moved into ``mcp_servers/custom/<slug>/`` (atomic swap with
   rollback on failure);
2. the registry overlay gets an entry marked ``aion_custom`` (env = manifest
   literals + credential placeholders built by the same helpers the Hub uses);
3. ``McpServerConfig`` is synced (credential mode/schema taken from the manifest,
   see ``integration``), cached agents and pooled workers are invalidated so the
   next chat turn uses the new code;
4. the action is written to ``audit_log`` (never with secrets).

Called by ``src/api/admin_custom_mcp.py``; ``remove_custom_artifacts`` is also
called by ``DELETE /admin/mcp/{name}``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import settings
from .manifest import Manifest
from .package import discard, load_staged, upload_src_dir
from .paths import custom_root, is_custom_config, server_dir, slug_conflict, versions_root

logger = logging.getLogger("aion.mcp_custom.install")

# One activation at a time: two admins activating the same slug concurrently would
# otherwise race on the folder swap and on the registry file.
_ACTIVATION_LOCK = asyncio.Lock()


class ActivationError(ValueError):
    """Activation refused; ``code`` is stable for the UI, ``message`` is for humans."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_registry_entry(
    manifest: Manifest,
    *,
    sha256: str,
    uploaded_by: str,
    previous: Optional[Dict[str, Any]] = None,
    deps_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Registry entry of a custom server (``mcp_registry.local.yaml``).

    ``deps_key``: folder under ``.deps/`` with the dependencies installed by the
    verification step (mounted read-only at ``/deps``); None when there are none.

    ``command``/``args`` are informative: the spawn policy (``runtime``) rebuilds
    them from ``aion_custom.entrypoint`` so an edit of the registry cannot point the
    process at another file. ``aion_custom`` keeps the manifest data the rest of
    AION needs without re-reading the file (credential mode/schema, env defaults).

    Values of ``env`` changed by the admin after a previous activation are kept
    when the new manifest still declares the key: the manifest provides defaults,
    the admin's configuration of this installation wins.
    """
    from ..mcp_integration_sync import (
        suggest_registry_env_for_org_shared,
        suggest_registry_env_for_per_user,
    )

    schema = manifest.credential_schema()
    network, network_source = _network_choice(manifest, previous)
    env: Dict[str, str] = dict(manifest.env)
    if previous and is_custom_config(previous):
        prev_env = previous.get("env") or {}
        prev_defaults = previous["aion_custom"].get("env_defaults") or {}
        for key in manifest.env:
            if key in prev_env and key in prev_defaults and prev_env[key] != prev_defaults[key]:
                env[key] = prev_env[key]

    # Credential placeholders, resolved only from the encrypted store at spawn time.
    if manifest.credentials.mode == "org_shared":
        env.update(suggest_registry_env_for_org_shared(schema))
    elif manifest.credentials.mode == "per_user":
        env.update(suggest_registry_env_for_per_user(manifest.slug, schema))

    return {
        "command": "python",
        "args": ["-u", f"custom/{manifest.slug}/{manifest.entrypoint}"],
        "description": manifest.description,
        "env": env,
        "aion_custom": {
            "name": manifest.name,
            "version": manifest.version,
            "runtime": manifest.runtime,
            "entrypoint": manifest.entrypoint,
            "credential_mode": manifest.credentials.mode,
            "credential_schema": schema,
            "env_defaults": dict(manifest.env),
            "sha256": sha256,
            "uploaded_by": uploaded_by,
            "uploaded_at": _now_iso(),
            "deps_key": deps_key,
            # Effective network allowlist (empty = no network), where it comes from
            # ("manifest" or "admin") and what the manifest asks for, so the Hub can
            # flag a new upload that requests different destinations.
            "network": network,
            "network_source": network_source,
            "network_manifest": list(manifest.network),
        },
    }


def _network_choice(manifest: Manifest, previous: Optional[Dict[str, Any]]) -> tuple:
    """Network allowlist of a (re)activated server and where it comes from.

    A list edited by the admin (MCP Hub) survives new uploads: the admin approved
    those destinations for this installation. Otherwise the manifest's list applies.
    Returns ``(entries, "admin" | "manifest")``.
    """
    prev_meta = previous["aion_custom"] if is_custom_config(previous) else {}
    if prev_meta.get("network_source") == "admin" and isinstance(prev_meta.get("network"), list):
        return list(prev_meta["network"]), "admin"
    return list(manifest.network), "manifest"


async def set_network_allowlist(slug: str, entries: List[str], *, actor: str) -> Dict[str, Any]:
    """Admin edit of the network allowlist of an installed custom server.

    Validates and normalizes the entries, rewrites the registry entry, restarts the
    server's workers (the next call runs with the new rules) and records the change
    in the audit log. Raises ``ActivationError`` for unknown servers or invalid entries.
    """
    from ..mcp_manager import mcp_manager
    from .egress import AllowlistError, normalize_allowlist

    try:
        allow = normalize_allowlist(entries)
    except AllowlistError as exc:
        raise ActivationError("network_invalid", str(exc)) from exc
    async with _ACTIVATION_LOCK:
        mcp_manager.load_registry()
        entry = mcp_manager._registry.get(slug)
        if not is_custom_config(entry):
            raise ActivationError("not_custom", f"'{slug}' is not a custom MCP server")
        updated = dict(entry)
        meta = dict(updated["aion_custom"])
        previous = meta.get("network")
        meta.update(network=allow, network_source="admin")
        updated["aion_custom"] = meta
        mcp_manager._registry_local[slug] = updated
        mcp_manager._rebuild_merged()
        mcp_manager.save_registry()
    await invalidate_runtime(slug)
    await _audit(actor, "mcp_custom.network", slug, {"from": previous, "to": allow})
    return {"server_slug": slug, "network": allow, "network_source": "admin"}


def _archive_name(version: str) -> str:
    """Archive folder name: version + timestamp (the same version may be re-uploaded)."""
    return f"{version}__{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"


def _prune_versions(slug: str) -> None:
    """Keep only the newest ``AION_CUSTOM_MCP_KEEP_VERSIONS`` archived versions."""
    root = versions_root() / slug
    if not root.is_dir():
        return
    archived = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in archived[settings.keep_versions():]:
        shutil.rmtree(old, ignore_errors=True)


def _swap_in(slug: str, staged_src: Path, current_version: Optional[str]) -> Optional[Path]:
    """Move the staged code into place, archiving the active version first.

    Returns the archive path of the previous version (None on first install). On
    failure the previous version is moved back before re-raising.
    """
    target = server_dir(slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    archived: Optional[Path] = None
    if target.exists():
        archived = versions_root() / slug / _archive_name(current_version or "unknown")
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(archived))
    try:
        shutil.move(str(staged_src), str(target))
    except Exception:
        if archived is not None and archived.exists() and not target.exists():
            shutil.move(str(archived), str(target))
        raise
    return archived


def _restore_previous(slug: str, archived: Optional[Path]) -> None:
    """Undo ``_swap_in`` after a later step failed (registry write)."""
    target = server_dir(slug)
    shutil.rmtree(target, ignore_errors=True)
    if archived is not None and archived.exists():
        shutil.move(str(archived), str(target))


async def invalidate_runtime(slug: str) -> None:
    """Make the next chat turn use the new code/config of ``slug``.

    Same effect as ``_invalidate_mcp_runtime`` in ``src/api/admin.py`` (not
    imported to avoid a circular import): drop cached agents (their tool list) and
    stop the pooled stdio workers of the server.
    """
    from ..main import clear_agent_cache
    from ..mcp_manager import mcp_manager

    clear_agent_cache()
    try:
        await mcp_manager.restart_workers_for_server(slug)
    except Exception:
        # The new version is already in place; idle cleanup will reap old workers.
        logger.exception("Failed to stop pooled workers of custom MCP '%s'", slug)


async def _audit(actor: str, operation: str, slug: str, payload: Dict[str, Any]) -> None:
    from ..data.audit import record_admin_action

    await record_admin_action(
        tenant_id=(os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip(),
        actor=actor,
        operation=operation,
        resource_type="mcp_server",
        resource_id=slug,
        payload=payload,
    )


async def activate(upload_id: str, *, actor: str, replace_same_version: bool = False) -> Dict[str, Any]:
    """Activate a reviewed upload. Raises ``ActivationError`` or ``UploadNotFound``.

    Side effects: filesystem swap under ``mcp_servers/custom``, registry overlay
    write, ``McpServerConfig`` upsert, agent cache/worker invalidation, audit row.
    """
    from ..mcp_integration_sync import sync_mcp_server_config_from_registry
    from ..mcp_manager import mcp_manager

    async with _ACTIVATION_LOCK:
        staged = await asyncio.to_thread(load_staged, upload_id)
        if staged.status == "invalid":
            raise ActivationError("upload_invalid", "the upload has blocking errors: " + "; ".join(staged.errors))
        if staged.manifest is None:
            raise ActivationError("manifest_required", "fill in the server details (manifest) before activating")
        # Only an upload proven to work in the jail (dependencies + probe) goes live.
        if staged.status == "verifying":
            raise ActivationError("verification_pending", "the package is still being verified: wait for it to finish")
        if staged.status != "ready":
            raise ActivationError(
                "verification_failed",
                "the package did not pass the verification: " + str((staged.build or {}).get("error") or "unknown error"),
            )
        manifest = Manifest.model_validate(staged.manifest)
        slug = manifest.slug

        # Re-check the slug now: the registry may have changed since the review.
        conflict = await asyncio.to_thread(slug_conflict, slug)
        if conflict:
            raise ActivationError("slug_conflict", conflict)
        mcp_manager.load_registry()
        previous = mcp_manager._registry.get(slug)
        current_version = previous["aion_custom"].get("version") if is_custom_config(previous) else None
        if current_version == manifest.version and not replace_same_version:
            raise ActivationError(
                "same_version",
                f"version {manifest.version} is already installed: confirm to replace it, or bump 'version'",
            )

        entry = build_registry_entry(
            manifest,
            sha256=staged.sha256,
            uploaded_by=actor,
            previous=previous,
            deps_key=(staged.build or {}).get("deps_key"),
        )

        # Code first, then registry: on registry failure restore the previous code.
        archived = await asyncio.to_thread(_swap_in, slug, upload_src_dir(upload_id), current_version)
        try:
            mcp_manager.load_registry()
            mcp_manager._registry_local[slug] = entry
            mcp_manager._remove_from_deleted_list(slug)
            mcp_manager._rebuild_merged()
            mcp_manager.save_registry()
        except Exception:
            await asyncio.to_thread(_restore_previous, slug, archived)
            raise

        await asyncio.to_thread(_write_install_marker, slug, manifest, staged.sha256, actor)
        await asyncio.to_thread(discard, upload_id)
        await asyncio.to_thread(_prune_versions, slug)
        await sync_mcp_server_config_from_registry(slug)
        await invalidate_runtime(slug)
        await _audit(
            actor,
            "mcp_custom.activate",
            slug,
            {
                "version": manifest.version,
                "previous_version": current_version,
                "sha256": staged.sha256,
                "source": staged.source_kind,
                "manifest_source": staged.manifest_source,
                "credential_mode": manifest.credentials.mode,
            },
        )
        logger.info("Custom MCP '%s' %s -> %s activated by %s", slug, current_version, manifest.version, actor)
        return {
            "server_slug": slug,
            "version": manifest.version,
            "previous_version": current_version,
            "credential_mode": manifest.credentials.mode,
            "config": entry,
        }


def list_custom_servers() -> List[Dict[str, Any]]:
    """Installed custom servers with version info, for the admin API."""
    from ..mcp_manager import mcp_manager

    mcp_manager.load_registry()
    out = []
    for slug, cfg in sorted(mcp_manager._registry.items()):
        if not is_custom_config(cfg):
            continue
        meta = cfg["aion_custom"]
        archive = versions_root() / slug
        out.append(
            {
                "server_slug": slug,
                "name": meta.get("name") or slug,
                "version": meta.get("version"),
                "runtime": meta.get("runtime", "python"),
                "credential_mode": meta.get("credential_mode", "none"),
                # Allowlist in force (anything but a list, e.g. a hand-edited
                # registry, means no network) and the one the manifest asks for.
                "network": meta.get("network") if isinstance(meta.get("network"), list) else [],
                "network_source": meta.get("network_source") or "manifest",
                "network_manifest": meta.get("network_manifest") if isinstance(meta.get("network_manifest"), list) else [],
                "uploaded_by": meta.get("uploaded_by"),
                "uploaded_at": meta.get("uploaded_at"),
                "code_present": server_dir(slug).is_dir(),
                "archived_versions": sorted(p.name.split("__")[0] for p in archive.iterdir() if p.is_dir())
                if archive.is_dir()
                else [],
            }
        )
    return out


# Written into the server folder at activation: proves the folder was created by
# AION's upload flow, so the orphan cleanup may delete it once the registry entry
# is gone. Folders without it (copied by hand) are never deleted automatically.
INSTALL_MARKER = ".aion-installed.json"


def _write_install_marker(slug: str, manifest: Manifest, sha256: str, actor: str) -> None:
    import json

    (server_dir(slug) / INSTALL_MARKER).write_text(
        json.dumps(
            {"slug": slug, "version": manifest.version, "sha256": sha256, "installed_by": actor, "installed_at": _now_iso()},
            indent=2,
        ),
        encoding="utf-8",
    )


def _force_rmtree(target: Path) -> bool:
    """Delete a folder tree, clearing read-only flags (Windows/OneDrive bind mounts).

    Returns True when the folder is gone. Never raises: a failure is logged and the
    caller reports it, instead of the old silent ``ignore_errors=True``.
    """
    import os
    import stat as _stat

    def _on_error(func, path, _exc):  # retry once after making the entry writable
        try:
            os.chmod(path, _stat.S_IWRITE | _stat.S_IREAD)
            func(path)
        except OSError:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(target, onexc=_on_error)
        else:  # pragma: no cover - the backend image runs Python 3.13
            shutil.rmtree(target, onerror=_on_error)
    except OSError as exc:
        logger.warning("Could not delete %s: %s", target, exc)
    return not target.exists()


def _staged_uploads_for(slug: str) -> List[Path]:
    """Staging folders of uploads that target ``slug`` (manifest slug or suggested slug)."""
    import json

    root = custom_root() / ".staging"
    out: List[Path] = []
    if not root.is_dir():
        return out
    for entry in root.iterdir():
        state = entry / "upload.json"
        try:
            data = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
        except (OSError, ValueError):
            continue
        manifest_slug = (data.get("manifest") or {}).get("slug")
        if slug in (manifest_slug, data.get("suggested_slug")):
            out.append(entry)
    return out


def has_custom_artifacts(slug: str) -> bool:
    """True when files of a custom server exist for ``slug`` (code or archived versions).

    Used by the delete endpoints even when the registry entry is no longer marked
    ``aion_custom`` (e.g. it was overwritten by an install): the files still belong
    to that slug and must go with it.
    """
    return server_dir(slug).is_dir() or (versions_root() / slug).is_dir()


def remove_custom_artifacts(slug: str) -> Dict[str, Any]:
    """Delete everything a custom server added: code, archived versions, pending
    uploads for the same slug and leftover containers.

    Called after the registry entry is removed (``DELETE /admin/mcp/{name}``,
    ``DELETE /admin/market/uninstall-zero/{slug}``) and by ``cleanup_orphans``.
    Every path is checked to stay under ``mcp_servers/custom`` before deletion.
    Returns what was removed and what could not be (shown to the admin).
    """
    root = custom_root().resolve()
    removed: List[str] = []
    failed: List[str] = []
    for target in (server_dir(slug), versions_root() / slug, *_staged_uploads_for(slug)):
        resolved = target.resolve()
        if root not in resolved.parents or not resolved.is_dir():
            continue
        rel = resolved.relative_to(root).as_posix()
        (removed if _force_rmtree(resolved) else failed).append(rel)
        logger.info("Custom MCP cleanup %s: %s", slug, rel)

    containers = 0
    from .runtime import container_isolation_available

    if container_isolation_available():
        from ..security.container_runtime import get_container_runtime

        containers = get_container_runtime().remove_custom_mcp_containers(slug)
    # Dependency folders are shared by content: drop only those nobody uses any more.
    from .verify import gc_deps

    deps_removed = gc_deps()
    return {"removed": removed, "failed": failed, "containers_removed": containers, "deps_removed": deps_removed}


def cleanup_orphans() -> Dict[str, Any]:
    """Remove leftovers of custom servers no longer in the registry.

    - expired uploads in ``.staging`` (never activated);
    - server folders carrying AION's install marker whose slug has no custom
      registry entry any more;
    - archived versions whose slug has neither a registry entry nor a code folder.

    Run at backend startup. Folders without the marker (copied by hand, to be
    activated later) are left untouched.
    """
    from ..mcp_manager import mcp_manager
    from .package import cleanup_expired

    mcp_manager.load_registry()
    custom_slugs = {s for s, cfg in mcp_manager._registry.items() if is_custom_config(cfg)}
    summary: Dict[str, Any] = {"expired_uploads": cleanup_expired(), "servers": {}}
    root = custom_root()
    if not root.is_dir():
        return summary
    for entry in root.iterdir():
        if entry.name.startswith(".") or not entry.is_dir() or entry.name in custom_slugs:
            continue
        if (entry / INSTALL_MARKER).is_file():
            summary["servers"][entry.name] = remove_custom_artifacts(entry.name)
    versions = versions_root()
    if versions.is_dir():
        for entry in versions.iterdir():
            if entry.is_dir() and entry.name not in custom_slugs and not server_dir(entry.name).exists():
                summary["servers"][entry.name] = remove_custom_artifacts(entry.name)
    from .verify import gc_deps

    summary["deps_removed"] = gc_deps()
    return summary


async def record_removal(actor: str, slug: str, version: Optional[str]) -> None:
    """Audit row for the deletion of a custom server."""
    await _audit(actor, "mcp_custom.delete", slug, {"version": version})
