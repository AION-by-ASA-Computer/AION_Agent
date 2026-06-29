"""Upload file nella workspace di sessione (chat-ui e altri client)."""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from src.session_workspace import list_dir, save_upload
from .auth_login import ChatAuthIdentity, require_chat_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])


@router.post("/sessions/{session_id}/upload")
async def upload_session_files(
    session_id: str,
    files: List[UploadFile] = File(...),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """Carica uno o più file in uploads/ per la sessione."""
    if not files:
        raise HTTPException(status_code=400, detail="Nessun file")

    import os
    otel_enabled = os.getenv("AION_OTEL_ENABLED", "0") == "1"
    tracer = None
    if otel_enabled:
        try:
            from opentelemetry import trace
            tracer = trace.get_tracer("aion.session")
        except ImportError:
            pass

    from contextlib import nullcontext
    span_ctx = nullcontext()
    if tracer:
        try:
            span_ctx = tracer.start_as_current_span("session.upload")
        except Exception:
            pass

    out = []
    with span_ctx as span:
        if span and span.is_recording():
            try:
                span.set_attribute("aion.session_id", session_id)
                span.set_attribute("upload.file_count", len(files))
                span.set_attribute("upload.filenames", [f.filename for f in files if f.filename])
                if _auth.identifier:
                    span.set_attribute("aion.user_id", _auth.identifier)
            except Exception:
                pass

        try:
            for f in files:
                data = await f.read()
                meta = save_upload(session_id, f.filename or "upload", data)
                out.append(meta)
            
            logger.info(
                "file_upload_success session_id=%s file_count=%d filenames=%s user_id=%s",
                session_id,
                len(files),
                [f.filename for f in files if f.filename],
                _auth.identifier or "anonymous",
                extra={
                    "session_id": session_id,
                    "file_count": len(files),
                    "filenames": [f.filename for f in files if f.filename],
                    "user_id": _auth.identifier or "anonymous",
                }
            )
        except ValueError as e:
            if span and span.is_recording():
                try:
                    from opentelemetry.trace import Status, StatusCode
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            if span and span.is_recording():
                try:
                    from opentelemetry.trace import Status, StatusCode
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                except Exception:
                    pass
            logger.exception("upload failed")
            raise HTTPException(status_code=500, detail=str(e)) from e
    return {"files": out}


@router.get("/sessions/{session_id}/files")
async def list_session_files(
    session_id: str,
    subdir: str = "uploads",
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """Elenco file (uploads, derived, workspace)."""
    try:
        rows = list_dir(session_id, subdir=subdir)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        # Tipico: AION_DATA_DIR=/app/data copiato da Docker ma API avviata sulla macchina host.
        logger.exception("session files list: storage error session=%s subdir=%s", session_id, subdir)
        raise HTTPException(
            status_code=503,
            detail=(
                "Session storage is not reachable or not writable. "
                "Check AION_DATA_DIR (on local dev use `data`, not `/app/data` from Docker). "
                f"Underlying error: {e!s}"
            ),
        ) from e
    return {"files": rows}


def _top_segment(rel: str) -> str:
    return (rel or "").strip().replace("\\", "/").split("/", 1)[0].lower()


@router.get("/sessions/{session_id}/download")
async def download_session_file(
    session_id: str,
    relative_path: str = Query(..., description="Path relativo, es. workspace/matricielle.csv"),
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """
    Scarica un file dalla cartella sessione (solo uploads/, derived/, workspace/).
    Percorso fisico sul server: DATA_DIR/sessions/<session_id>/...
    """
    from src.session_workspace import safe_resolve

    rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    if rel.startswith("."):
        raise HTTPException(status_code=400, detail="Path non consentito per il download")
    top = _top_segment(rel)
    if "/" in rel:
        if top not in ("uploads", "derived", "workspace", "unpacked"):
            raise HTTPException(status_code=400, detail="Path non consentito per il download")
    try:
        path = safe_resolve(session_id, rel, must_exist=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File non trovato") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Non è un file")
    mime, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        filename=path.name,
        media_type=mime or "application/octet-stream",
    )


@router.get("/sessions/{session_id}/events/stream")
async def session_events_sse(
    session_id: str,
    _auth: ChatAuthIdentity = Depends(require_chat_auth),
):
    """SSE: eventi Redis di sessione (es. orchestration_plan_approved) per chat-ui.

    Auth: quando ``AION_CHAT_PASSWORD_AUTH=1`` il token va passato in query
    string come ``?access_token=...`` perche' ``EventSource`` non supporta
    header custom (gestito da ``require_chat_auth``).
    """

    async def gen():
        from src.runtime.redis_client import redis_drain_session_events

        try:
            while True:
                events = await redis_drain_session_events(session_id.strip(), max_items=25)
                for ev in events:
                    yield {"event": "session_event", "data": json.dumps(ev)}
                await asyncio.sleep(0.45)
        except asyncio.CancelledError:
            raise

    return EventSourceResponse(
        gen(),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
