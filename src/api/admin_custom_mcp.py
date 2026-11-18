"""Admin endpoints for customer-built MCP servers (``/admin/mcp-custom``).

Flow driven by the admin-ui "Upload MCP" dialog (MCP Hub):

1. ``POST /uploads``: upload a ``.py`` or ``.zip``; the package is validated and
   staged, the response is the review (files, manifest, variables check, warnings,
   review notes, blocking errors).
2. ``PUT /uploads/{id}/manifest``: for uploads without ``aion-mcp.yaml``, the admin
   fills the server details in a form; AION generates the manifest.
3. ``POST /uploads/{id}/activate``: the server goes live (code in
   ``mcp_servers/custom/<slug>/``, registry entry, credential policy). The UI then
   opens the existing configuration dialog (credentials, availability, profiles).

Included by ``src/api/admin.py`` under the ``/admin`` router, so every route
inherits ``require_admin_role``. Uploading/activating requires
``AION_CUSTOM_MCP_ENABLED=1`` (set in ``.env`` by whoever runs the server); listing,
config and the template are always readable. Logic lives in ``src/mcp_custom``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.api.auth_login import ChatAuthIdentity, require_admin_role
from src.mcp_custom import settings
from src.mcp_custom.egress import MAX_ENTRIES as MAX_NETWORK_ENTRIES
from src.mcp_custom.install import ActivationError, activate, list_custom_servers, set_network_allowlist
from src.mcp_custom.manifest import ManifestError, SUPPORTED_RUNTIMES, manifest_json_schema
from src.mcp_custom.package import (
    UploadError,
    UploadNotFound,
    discard,
    load_staged,
    stage_upload,
    submit_manifest,
)
from src.mcp_custom.template import guide_templates
from src.mcp_custom.verify import cancel_verification, recover_interrupted, start_verification

logger = logging.getLogger("aion.api.admin_custom_mcp")

router = APIRouter(prefix="/mcp-custom", tags=["admin-mcp-custom"])


def _actor(auth: ChatAuthIdentity) -> str:
    """Who performed the action, for upload metadata and audit."""
    return auth.identifier or auth.user_row_id or "admin"


def _require_enabled() -> None:
    """403 unless uploads are enabled in ``.env`` (and the kill switch is off)."""
    if not settings.upload_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "custom_mcp_disabled",
                "message": "Custom MCP upload is disabled: set AION_CUSTOM_MCP_ENABLED=1 in .env and restart.",
            },
        )
    if settings.force_disabled():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "custom_mcp_force_disabled",
                "message": "Custom MCP servers are disabled by AION_CUSTOM_MCP_FORCE_DISABLE=1.",
            },
        )


def _not_found(upload_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": "upload_not_found", "message": f"Upload {upload_id} not found or expired."},
    )


@router.get("/config")
async def get_custom_mcp_config() -> Dict[str, Any]:
    """Feature state and limits, read by admin-ui to show/hide the upload button."""
    from src.security.container_runtime import get_container_runtime

    runtime = get_container_runtime()
    return {
        "enabled": settings.upload_enabled(),
        "force_disabled": settings.force_disabled(),
        # Custom servers need container isolation; without it they only start with
        # the development flag (the UI shows a warning banner in that case).
        "sandbox_available": runtime.is_available(),
        "container_runtime": runtime.runtime,
        "allow_unsandboxed": settings.allow_unsandboxed(),
        "max_upload_mb": settings.max_upload_bytes() // (1024 * 1024),
        "max_files": settings.max_files(),
        "runtimes": list(SUPPORTED_RUNTIMES),
        # Maximum entries of a server's network allowlist (editor in the MCP Hub).
        "network_max_entries": MAX_NETWORK_ENTRIES,
    }


@router.get("")
async def list_custom_mcp_servers() -> Dict[str, Any]:
    """Installed custom servers (version, uploader, archived versions)."""
    return {"servers": await asyncio.to_thread(list_custom_servers)}


@router.get("/guide-template")
async def get_guide_template() -> Dict[str, str]:
    """Snippets shown by the admin-ui guide: ``aion-mcp.yaml`` template and a minimal ``server.py``."""
    return guide_templates()


@router.get("/manifest-schema")
async def get_manifest_schema() -> Dict[str, Any]:
    """JSON Schema of ``aion-mcp.yaml`` (editor autocompletion, docs)."""
    return manifest_json_schema()


@router.post("/uploads")
async def upload_custom_mcp(
    file: UploadFile = File(...),
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Validate and stage an uploaded ``.py``/``.zip``; returns the review."""
    _require_enabled()
    limit = settings.max_upload_bytes()
    # Read one byte more than the limit so oversize files are rejected without
    # buffering arbitrarily large bodies.
    data = await file.read(limit + 1)
    try:
        staged = await asyncio.to_thread(stage_upload, file.filename or "", data, actor=_actor(auth))
    except UploadError as exc:
        raise HTTPException(status_code=400, detail={"error": "upload_rejected", "message": str(exc)}) from exc
    logger.info("Custom MCP upload %s staged by %s (%s, %s)", staged.upload_id, _actor(auth), staged.source_kind, staged.status)
    # With a valid manifest the verification (dependencies + probe in the jail) starts
    # right away; admin-ui polls GET /uploads/{id} until it is ready or failed.
    if staged.status == "verifying":
        start_verification(staged.upload_id)
    return staged.to_public()


@router.get("/uploads/{upload_id}")
async def get_custom_mcp_upload(upload_id: str) -> Dict[str, Any]:
    """Current review state of an upload (polled by admin-ui while verifying)."""
    try:
        staged = await asyncio.to_thread(load_staged, upload_id)
    except UploadNotFound as exc:
        raise _not_found(upload_id) from exc
    return recover_interrupted(staged).to_public()


@router.post("/uploads/{upload_id}/verify")
async def verify_custom_mcp_upload(upload_id: str) -> Dict[str, Any]:
    """Run the verification again (after a failure or an interrupted run)."""
    _require_enabled()
    try:
        staged = await asyncio.to_thread(load_staged, upload_id)
    except UploadNotFound as exc:
        raise _not_found(upload_id) from exc
    if staged.status not in ("verifying", "verify_failed"):
        raise HTTPException(
            status_code=409,
            detail={"error": "not_verifiable", "message": f"nothing to verify in status '{staged.status}'"},
        )
    start_verification(upload_id)
    return (await asyncio.to_thread(load_staged, upload_id)).to_public()


@router.put("/uploads/{upload_id}/manifest")
async def put_custom_mcp_manifest(upload_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Attach the manifest filled in the admin-ui form; returns the updated review."""
    _require_enabled()
    try:
        staged = await asyncio.to_thread(submit_manifest, upload_id, body)
    except UploadNotFound as exc:
        raise _not_found(upload_id) from exc
    except ManifestError as exc:
        raise HTTPException(status_code=422, detail={"error": "manifest_invalid", "errors": exc.errors}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error": "manifest_locked", "message": str(exc)}) from exc
    if staged.status == "verifying":
        start_verification(upload_id)
    return staged.to_public()


class ActivateBody(BaseModel):
    """Body of ``POST /uploads/{id}/activate``."""

    # Required to overwrite an installed server with the same version number.
    replace_same_version: bool = False


@router.post("/uploads/{upload_id}/activate")
async def activate_custom_mcp(
    upload_id: str,
    body: ActivateBody | None = None,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Put a reviewed upload live; returns slug, versions and the registry entry."""
    _require_enabled()
    try:
        return await activate(
            upload_id,
            actor=_actor(auth),
            replace_same_version=bool(body and body.replace_same_version),
        )
    except UploadNotFound as exc:
        raise _not_found(upload_id) from exc
    except ActivationError as exc:
        raise HTTPException(status_code=409, detail={"error": exc.code, "message": exc.message}) from exc


@router.delete("/uploads/{upload_id}")
async def discard_custom_mcp_upload(upload_id: str) -> Dict[str, Any]:
    """Drop an upload that will not be activated (stopping its verification)."""
    cancel_verification(upload_id)
    try:
        await asyncio.to_thread(discard, upload_id)
    except UploadNotFound as exc:
        raise _not_found(upload_id) from exc
    return {"ok": True}


class NetworkBody(BaseModel):
    """Body of ``PUT /servers/{slug}/network``: the full allowlist (may be empty)."""

    allow: List[str] = Field(default_factory=list)


@router.put("/servers/{slug}/network")
async def put_custom_mcp_network(
    slug: str,
    body: NetworkBody,
    auth: ChatAuthIdentity = Depends(require_admin_role),
) -> Dict[str, Any]:
    """Replace the network allowlist of an installed custom server.

    Only the listed destinations (host names, IPs or subnets, optional ports; see
    ``src/mcp_custom/egress.py``) are reachable; an empty list means no network.
    The admin's list survives new uploads of the server, restarts its workers and
    is written to the audit log. 422 with the validation message on bad entries.
    """
    try:
        return await set_network_allowlist(slug, body.allow, actor=_actor(auth))
    except ActivationError as exc:
        status = 404 if exc.code == "not_custom" else 422
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": exc.message}) from exc
