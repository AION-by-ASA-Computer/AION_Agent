"""Admin API for the local speech-to-text model (admin-ui → Settings → Audio).

Included in the ``/admin`` router, so ``require_admin_role`` is inherited. The
model choice itself (``AION_STT_LOCAL_MODEL``) is saved through the generic
``/admin/settings`` endpoint; this router only tells admin-ui which models are
already on disk and lets the admin download one ahead of time. Without the
pre-download, the first transcription after switching model would spend its
whole time budget fetching hundreds of MB from Hugging Face.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from src.tools.audio_transcribe import (
    LOCAL_MODEL_CHOICES,
    download_local_model,
    find_local_model,
    is_remote_stt_enabled,
    local_model_name,
)

logger = logging.getLogger("aion.admin_stt")

router = APIRouter(prefix="/stt", tags=["admin_stt"])

# State of the single background download. In-process is enough: the backend
# runs with --workers 1 (see CLAUDE.md), and a restart simply forgets it while
# the files already fetched stay on disk for the next attempt.
_download: Dict[str, Any] = {"model": None, "state": "idle", "error": None}
_download_task: Optional[asyncio.Task] = None


def _status() -> Dict[str, Any]:
    """Models offered in admin-ui with their on-disk status, plus the download state."""
    current = local_model_name()
    names = list(LOCAL_MODEL_CHOICES)
    # A model set by hand in .env (another faster-whisper name or a directory)
    # is still reported, so admin-ui can show it instead of a wrong selection.
    if current not in names:
        names.append(current)
    return {
        "mode": "remote" if is_remote_stt_enabled() else "local",
        "current": current,
        "models": [
            {
                "name": name,
                "installed": find_local_model(name) is not None,
                "custom": name not in LOCAL_MODEL_CHOICES,
            }
            for name in names
        ],
        "download": dict(_download),
    }


async def _run_download(name: str) -> None:
    """Background task: fetch the model files and record the outcome."""
    try:
        await asyncio.to_thread(download_local_model, name)
        _download.update(state="done", error=None)
        logger.info("STT model %s downloaded", name)
    except Exception as exc:  # network, disk full, Hugging Face errors
        logger.exception("STT model %s download failed", name)
        _download.update(state="error", error=str(exc)[:500])


@router.get("/local-models")
async def get_local_models() -> Dict[str, Any]:
    """Which local models are available on this server and what is being downloaded."""
    return _status()


@router.post("/local-models/{name}/download")
async def download_model(name: str) -> Dict[str, Any]:
    """Start downloading a model in the background; poll ``GET /local-models``.

    Only the curated names are accepted, so this endpoint cannot be used to
    fetch arbitrary Hugging Face repositories or write to arbitrary paths.
    """
    global _download_task
    if name not in LOCAL_MODEL_CHOICES:
        raise HTTPException(status_code=400, detail="unknown_model")
    if _download["state"] == "running":
        raise HTTPException(status_code=409, detail="download_in_progress")
    if find_local_model(name) is None:
        _download.update(model=name, state="running", error=None)
        _download_task = asyncio.create_task(_run_download(name))
    return _status()
