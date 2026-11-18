"""Verification of a staged custom MCP upload, inside the jail.

Model: **accept everything, contain everything**. AION does not decide which
packages or instructions a customer's server may use; it runs the code where
there is nothing private to read and nothing outside to damage. This module
proves an upload works under exactly those conditions before it can be
activated:

1. **dependencies** (``requirements.txt`` / ``pyproject.toml``, any package): installed
   by ``pip --target`` in a *build container* with the same jail (no capabilities,
   unprivileged user, read-only root, package code mounted read-only, only the
   target folder writable). By default **wheels only**: installing a wheel never
   runs code of the package, so while the build container has network access only
   pip runs (``AION_CUSTOM_MCP_ALLOW_SOURCE_BUILDS=1`` allows setup.py builds, still
   jailed). The result goes to ``mcp_servers/custom/.deps/<key>/``, shared by
   identical requirement sets and mounted read-only at ``/deps`` at run time;
2. **probe**: the server is started in its runtime jail (the manifest's network
   allowlist, no credentials) and must answer the MCP handshake and ``list_tools``. Import
   errors, missing packages and crashes surface here with the server's stderr.

The steps run in a background task started by the admin API; state and logs are
stored in the upload's ``upload.json`` (``StagedUpload.build``) and polled by
admin-ui. Only a ``ready`` upload can be activated (``install.activate``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import settings
from .manifest import Manifest
from .package import NORMALIZED_REQUIREMENTS, StagedUpload, _save_state, load_staged, upload_src_dir
from .paths import deps_root

logger = logging.getLogger("aion.mcp_custom.verify")

DEPS_MARKER = ".aion-deps.json"
LOG_TAIL_CHARS = 12_000

# Running verifications (single uvicorn worker): upload_id -> task. A state left
# "running" without a task means the backend restarted mid-verification.
_TASKS: Dict[str, asyncio.Task] = {}


class VerifyError(RuntimeError):
    """A verification step failed; ``log`` holds the output shown to the admin."""

    def __init__(self, message: str, log: str = ""):
        super().__init__(message)
        self.log = log


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(text: str) -> str:
    return text if len(text) <= LOG_TAIL_CHARS else "…\n" + text[-LOG_TAIL_CHARS:]


# ───────────────────────── dependency store ─────────────────────────


def _image() -> str:
    return (os.environ.get("AION_SANDBOX_CONTAINER_IMAGE") or "aion/sandbox:latest").strip()


def deps_key(requirements: List[str]) -> str:
    """Content key of a dependency set: same requirements + image + build mode, same folder."""
    material = "\n".join([_image(), f"source_builds={settings.allow_source_builds()}", *requirements])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def deps_path(key: str) -> Path:
    return deps_root() / key


def deps_ready(key: str) -> bool:
    """True when the dependency folder was completely built (marker written last)."""
    return bool(key) and (deps_path(key) / DEPS_MARKER).is_file()


async def _run(argv: List[str], env: Dict[str, str], timeout: int, cwd: Optional[str] = None) -> tuple[int, str]:
    """Run a command, merged stdout/stderr, killed after ``timeout`` seconds."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd=cwd,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise VerifyError(f"dependency installation timed out after {timeout}s")
    return proc.returncode or 0, out.decode("utf-8", errors="replace")


async def _build_deps(staged: StagedUpload, slug: str, key: str, in_container: bool) -> str:
    """Install the declared dependencies into ``.deps/<key>``; returns the build log."""
    final = deps_path(key)
    tmp = deps_root() / f"{key}.building-{staged.upload_id}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    # The build container runs as an unprivileged user that must write here.
    os.chmod(tmp, 0o777)
    src = upload_src_dir(staged.upload_id)

    if in_container:
        from ..security.container_runtime import get_container_runtime

        from .ca import jail_ca_bundle

        argv, env = get_container_runtime().build_custom_mcp_deps_command(
            slug,
            src_path=src,
            deps_path=tmp,
            requirements_rel=NORMALIZED_REQUIREMENTS,
            allow_source_builds=settings.allow_source_builds(),
            ca_path=jail_ca_bundle(),
        )
    else:
        # Development fallback without a container engine (AION_CUSTOM_MCP_ALLOW_UNSANDBOXED=1).
        from .runtime import base_process_env

        uv = shutil.which("uv")
        pip = [uv, "pip", "install", "--python", sys.executable] if uv else [sys.executable, "-m", "pip", "install", "--no-input"]
        argv = [*pip, "--target", str(tmp)]
        if not settings.allow_source_builds():
            argv.append("--only-binary=:all:")
        argv.extend(["-r", str(src / NORMALIZED_REQUIREMENTS)])
        env = {**base_process_env(), "PIP_NO_CACHE_DIR": "1"}

    try:
        code, log = await _run(argv, env, settings.build_timeout_seconds())
    except VerifyError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if code != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        hint = ""
        if "only-binary" in log or "no matching distribution" in log.lower():
            hint = (
                " A package may have no wheel for this platform: source builds are disabled "
                "(AION_CUSTOM_MCP_ALLOW_SOURCE_BUILDS=1 enables them)."
            )
        raise VerifyError(f"dependency installation failed (exit code {code}).{hint}", _tail(log))

    # Marker last: a folder without it is an interrupted build and is never used.
    (tmp / DEPS_MARKER).write_text(
        json.dumps(
            {
                "requirements": staged.requirements,
                "image": _image(),
                "isolated": in_container,
                "built_at": _now(),
                "built_for": slug,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if final.exists():  # another upload built the same set meanwhile
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        tmp.rename(final)
    return _tail(log)


# ───────────────────────── probe ─────────────────────────


async def _probe(staged: StagedUpload, manifest: Manifest, deps_dir: Optional[Path], in_container: bool) -> List[Dict[str, str]]:
    """Start the staged server like at run time (no credentials) and list its tools."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from .ca import jail_ca_bundle
    from .runtime import base_process_env, finalize_process_env, network_allowlist

    src = upload_src_dir(staged.upload_id)
    ca_path = jail_ca_bundle()
    env = base_process_env()
    env.update(manifest.env)
    env = finalize_process_env(env, in_container=in_container, deps_dir=deps_dir, ca_path=ca_path)
    if in_container:
        from ..security.container_runtime import get_container_runtime

        command, args, spawn_env = get_container_runtime().build_custom_mcp_spawn(
            manifest.slug,
            server_path=src,
            entrypoint=manifest.entrypoint,
            env=env,
            deps_path=deps_dir,
            network_allow=network_allowlist(None, manifest.network),
            ca_path=ca_path,
        )
        params = StdioServerParameters(command=command, args=args, env=spawn_env)
    else:
        params = StdioServerParameters(
            command=sys.executable, args=["-u", str(src / manifest.entrypoint)], env=env, cwd=str(src)
        )

    # The server's stderr (tracebacks, missing imports) is what the admin needs to see.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        try:
            async with asyncio.timeout(settings.probe_timeout_seconds()):
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.list_tools()
        except BaseException as exc:  # noqa: BLE001 - report any failure of the probe
            if isinstance(exc, asyncio.CancelledError) and asyncio.current_task().cancelling():
                raise
            errlog.seek(0)
            stderr = errlog.read()
            # The last stderr line of the server (e.g. "ModuleNotFoundError: No module
            # named 'x'") explains far better than the MCP client's exception group.
            last_line = next((ln.strip() for ln in reversed(stderr.splitlines()) if ln.strip()), "")
            if isinstance(exc, TimeoutError):
                reason = "it did not answer in time"
            elif last_line:
                reason = last_line
            else:
                reason = f"{type(exc).__name__}: {exc}"
            raise VerifyError(f"the server did not start correctly: {reason}", _tail(stderr))
    return [{"name": t.name, "description": (t.description or "")[:300]} for t in result.tools]


# ───────────────────────── orchestration ─────────────────────────


def _update(upload_id: str, **fields: Any) -> StagedUpload:
    staged = load_staged(upload_id)
    staged.build = {**(staged.build or {}), **fields}
    _save_state(staged)
    return staged


async def run_verification(upload_id: str) -> None:
    """Dependency build + probe for one upload; result stored in ``upload.json``."""
    from .runtime import container_isolation_available

    staged = load_staged(upload_id)
    if staged.errors or staged.manifest is None:
        return
    manifest = Manifest.model_validate(staged.manifest)
    started = time.monotonic()
    in_container = container_isolation_available()
    _update(upload_id, status="running", step="dependencies", started_at=_now(), isolated=in_container, error=None, log="")
    try:
        if not in_container and not settings.allow_unsandboxed():
            raise VerifyError(
                "no container engine available: custom servers are verified and run only in an isolated container"
            )
        deps_dir: Optional[Path] = None
        key = ""
        log = ""
        if staged.requirements:
            key = deps_key(staged.requirements)
            if deps_ready(key):
                log = "Dependencies already installed for this exact set of requirements: reused."
            else:
                log = await _build_deps(staged, manifest.slug, key, in_container)
            deps_dir = deps_path(key)
        # Network allowlist: names that do not resolve are reported in the log
        # shown to the admin (the server is still installable).
        if manifest.network:
            from .egress import parse_allowlist, resolve

            egress = await asyncio.to_thread(resolve, parse_allowlist(manifest.network))
            notes = [f"Network: {w}" for w in egress.warnings]
            if notes:
                log = "\n".join([*notes, log]).strip()
        _update(upload_id, step="probe", deps_key=key or None, log=log)
        tools = await _probe(staged, manifest, deps_dir, in_container)
        if not tools:
            raise VerifyError("the server started but exposes no tools (no function decorated with @mcp.tool())")
        _update(
            upload_id,
            status="ok",
            step=None,
            tools=tools,
            finished_at=_now(),
            duration_s=round(time.monotonic() - started, 1),
        )
    except VerifyError as exc:
        _update(upload_id, status="failed", error=str(exc), log=exc.log or "", finished_at=_now())
    except Exception as exc:  # unexpected: keep the upload reviewable
        logger.exception("Verification of custom MCP upload %s failed", upload_id)
        _update(upload_id, status="failed", error=f"unexpected error: {exc}", finished_at=_now())


def start_verification(upload_id: str) -> None:
    """Schedule ``run_verification`` (no-op when one is already running for this upload)."""
    task = _TASKS.get(upload_id)
    if task is not None and not task.done():
        return
    task = asyncio.create_task(run_verification(upload_id), name=f"mcp-custom-verify-{upload_id[:8]}")
    _TASKS[upload_id] = task
    task.add_done_callback(lambda _t: _TASKS.pop(upload_id, None))


def recover_interrupted(staged: StagedUpload) -> StagedUpload:
    """Mark as failed a verification left "running" by a backend restart."""
    status = (staged.build or {}).get("status")
    if status in ("running", "pending") and staged.upload_id not in _TASKS:
        return _update(
            staged.upload_id,
            status="failed",
            error="verification interrupted (backend restarted): run it again",
        )
    return staged


def cancel_verification(upload_id: str) -> None:
    """Stop a running verification (upload discarded)."""
    task = _TASKS.pop(upload_id, None)
    if task is not None and not task.done():
        task.cancel()


def referenced_deps_keys() -> set:
    """Dependency folders still in use: active servers and staged uploads."""
    from ..mcp_manager import mcp_manager
    from .paths import is_custom_config, staging_root

    keys = set()
    mcp_manager.load_registry()
    for cfg in mcp_manager._registry.values():
        if is_custom_config(cfg) and cfg["aion_custom"].get("deps_key"):
            keys.add(str(cfg["aion_custom"]["deps_key"]))
    root = staging_root()
    if root.is_dir():
        for state in root.glob("*/upload.json"):
            try:
                key = (json.loads(state.read_text(encoding="utf-8")).get("build") or {}).get("deps_key")
            except (OSError, ValueError):
                continue
            if key:
                keys.add(str(key))
    return keys


def gc_deps(max_building_age_s: int = 2 * 3600) -> List[str]:
    """Delete dependency folders no server or upload uses; returns their names.

    Folders of builds in progress (``<key>.building-<id>``) are kept unless stale.
    Called after a server is deleted and at backend startup.
    """
    root = deps_root()
    if not root.is_dir():
        return []
    keep = referenced_deps_keys()
    removed: List[str] = []
    now = time.time()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if ".building-" in entry.name:
            if now - entry.stat().st_mtime < max_building_age_s:
                continue
        elif entry.name in keep:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry.name)
    return removed
