"""Admin API: one-click AION upgrade from the admin-ui (``/admin/update/*``).

The backend cannot upgrade the stack it runs in, so these endpoints are a thin,
admin-only proxy towards the ``aion-updater`` sidecar (``docker/updater/server.py``,
service ``updater`` in ``docker-compose.ghcr.yml``), reached over the internal
``aion_net`` network with the shared ``AION_UPDATER_TOKEN``.

Used by:
- ``admin-ui/components/VersionUpdateBanner.tsx`` ("Update now" button),
- ``admin-ui/components/update/UpdateProgressOverlay.tsx`` (status polling),
- ``src/api/version_check.py`` (``fetch_update_plan`` for the banner).

Docs: ``docs/deployment/self-update.md``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.data.audit import record_admin_action

logger = logging.getLogger("aion.api.admin_update")
router = APIRouter(prefix="/admin/update", tags=["admin_update"])

# Public release page linked from the confirmation dialog for every hop.
_RELEASE_URL = "https://github.com/AION-by-ASA-Computer/AION_Agent/releases/tag/v{version}"
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Timeouts (seconds). /plan may run `install.sh upgrade --plan` (GitHub API
# call) on a cache miss in the sidecar; /status and /upgrade answer fast
# (/upgrade recomputes the plan before spawning the run, hence the same budget).
_PLAN_TIMEOUT = 30.0
_STATUS_TIMEOUT = 5.0
_START_TIMEOUT = 30.0


class UpdaterUnavailable(Exception):
    """The sidecar is not configured (no token) or cannot be reached.

    ``reason`` is ``not_configured`` or ``unreachable``; the admin-ui hides the
    "Update now" button in both cases.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _tenant_id() -> str:
    """Tenant used for audit rows (same convention as the other admin routers)."""
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()


def _updater_url() -> str:
    """Base URL of the sidecar; the default matches the compose service name."""
    return (os.getenv("AION_UPDATER_URL") or "http://updater:8090").rstrip("/")


def _updater_token() -> str:
    """Shared secret written in ``.env`` by install.sh (``_ensure_updater_env``)."""
    return (os.getenv("AION_UPDATER_TOKEN") or "").strip()


def updater_configured() -> bool:
    """True when the backend has a token to talk to the sidecar."""
    return bool(_updater_token())


async def _call_updater(
    method: str, path: str, *, timeout: float, json_body: Optional[Dict[str, Any]] = None
) -> httpx.Response:
    """Send one authenticated request to the sidecar.

    Raises UpdaterUnavailable when there is no token or on network errors; the
    caller handles the HTTP status of the returned response.
    """
    token = _updater_token()
    if not token:
        raise UpdaterUnavailable("not_configured")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(
                method,
                f"{_updater_url()}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
    except httpx.HTTPError as exc:
        logger.debug("admin_update: updater %s %s failed: %s", method, path, exc)
        raise UpdaterUnavailable("unreachable") from exc


def _with_release_links(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Add ``hops: [{version, release_url}]`` for the confirmation dialog.

    The final ``local`` hop (hybrid local-build mode) has no release page.
    """
    hops = []
    for version in plan.get("chain") or []:
        url = _RELEASE_URL.format(version=version) if _SEMVER_RE.match(str(version)) else None
        hops.append({"version": version, "release_url": url})
    return {**plan, "hops": hops}


async def fetch_update_plan() -> Optional[Dict[str, Any]]:
    """Return the sidecar's hop plan, or None when self-update is unavailable.

    Never raises: used by ``/admin/version-check``, which falls back to the
    GitHub API when the sidecar is not deployed.
    """
    try:
        resp = await _call_updater("GET", "/plan", timeout=_PLAN_TIMEOUT)
    except UpdaterUnavailable:
        return None
    if resp.status_code != 200:
        logger.info("admin_update: updater /plan returned %s", resp.status_code)
        return None
    try:
        return _with_release_links(resp.json())
    except ValueError:
        return None


def _error_detail(resp: httpx.Response) -> Dict[str, Any]:
    """Normalize a sidecar error body (``{error, detail}``) into an HTTPException detail."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return {
        "code": body.get("error") or f"updater_http_{resp.status_code}",
        "message": body.get("detail") or "",
    }


@router.get("/status")
async def get_update_status(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Current upgrade status (polled every few seconds by the admin-ui overlay).

    Returns ``{"supported": false, "reason": ...}`` instead of an error when the
    sidecar is missing, so the admin-ui can simply hide the feature.
    """
    try:
        resp = await _call_updater("GET", "/status", timeout=_STATUS_TIMEOUT)
    except UpdaterUnavailable as exc:
        return {"supported": False, "reason": exc.reason}
    if resp.status_code != 200:
        return {"supported": False, "reason": f"updater_http_{resp.status_code}"}
    return resp.json()


@router.get("/plan")
async def get_update_plan(
    refresh: bool = False,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Hop chain the "Update now" button would apply (current → … → target).

    ``refresh=true`` bypasses the sidecar's plan cache (used by the
    confirmation dialog so it never shows a stale chain).
    """
    try:
        resp = await _call_updater(
            "GET", "/plan?refresh=1" if refresh else "/plan", timeout=_PLAN_TIMEOUT
        )
    except UpdaterUnavailable as exc:
        raise HTTPException(503, detail={"code": f"updater_{exc.reason}"}) from exc
    if resp.status_code != 200:
        raise HTTPException(502, detail=_error_detail(resp))
    return _with_release_links(resp.json())


@router.post("/start", status_code=202)
async def start_update(
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Ask the sidecar to apply every pending hop up to the latest version.

    Side effects: the sidecar starts ``install.sh upgrade`` (backups, image
    pulls, migrations, stack restarts — this backend included); an
    ``update.start`` audit row is written once the sidecar accepted the run.
    Errors: 409 ``upgrade_running``/``upgrade_locked``, 404 ``no_update``,
    502 ``plan_failed``, 503 when the sidecar is unavailable.
    """
    try:
        resp = await _call_updater(
            "POST",
            "/upgrade",
            timeout=_START_TIMEOUT,
            json_body={"requested_by": auth.identifier},
        )
    except UpdaterUnavailable as exc:
        raise HTTPException(503, detail={"code": f"updater_{exc.reason}"}) from exc
    if resp.status_code != 202:
        # Propagate meaningful client errors as-is; anything else is a gateway error.
        status = resp.status_code if resp.status_code in (404, 409) else 502
        raise HTTPException(status, detail=_error_detail(resp))

    status_body = resp.json()
    await record_admin_action(
        tenant_id=_tenant_id(),
        actor=auth.identifier,
        operation="update.start",
        resource_type="aion_version",
        resource_id=str(status_body.get("target") or ""),
        payload={
            "from": status_body.get("current"),
            "to": status_body.get("target"),
            "chain": status_body.get("chain"),
            "mode": status_body.get("mode"),
        },
    )
    logger.info(
        "Upgrade %s -> %s requested by %s",
        status_body.get("current"),
        status_body.get("target"),
        auth.identifier,
    )
    return status_body
