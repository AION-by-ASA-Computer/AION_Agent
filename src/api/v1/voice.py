"""Voice dictation for chat-ui: a short recording in, plain text out.

The microphone button in the chat-ui composer posts its recording here and puts
the returned text in the textarea, where the user edits and sends it. The audio
goes through the same engines as the ``stt`` MCP server
(``src/tools/audio_transcribe.py``) but in-process: one faster-whisper model is
shared by every user instead of one per session worker, and the recording is
written to a temporary directory that is removed right after, so it never lands
in the session ``uploads/`` (which would attach it to the next chat message).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.api.auth.scopes import Scope
from src.api.auth_login import ChatAuthIdentity, require_chat_scope
from src.tools.audio_transcribe import (
    STT_JOB_LOCK,
    build_engine_from_env,
    find_local_model,
    is_remote_stt_enabled,
    local_model_name,
    resolve_language,
    transcribe_audio_to_text,
)

logger = logging.getLogger("aion.api.voice")

router = APIRouter(prefix="/voice", tags=["v1-voice"])

_ERROR_STATUS = {
    "too_large": 413,
    "too_long": 422,
    "not_audio": 422,
    "empty": 422,
    "decoder_unavailable": 503,
    "engine_failed": 503,
}

_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _max_seconds() -> int:
    return max(1, _env_int("AION_STT_DICTATION_MAX_SEC", 300))


def _max_bytes() -> int:
    return max(1, _env_int("AION_STT_DICTATION_MAX_BYTES", 10 * 1024 * 1024))


def _engine_available() -> bool:
    """Remote service configured, or local faster-whisper with its model on disk.

    A local model that is not downloaded yet counts as unavailable: the first
    dictation would otherwise wait for hundreds of MB from Hugging Face. The
    admin downloads it from admin-ui (Settings → Audio).
    """
    if is_remote_stt_enabled():
        return True
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return find_local_model(local_model_name()) is not None


def _enabled() -> bool:
    flag = os.environ.get("AION_CHAT_VOICE_INPUT", "1").strip().lower()
    return flag not in ("0", "false", "no", "off") and _engine_available()


@router.get("/status")
async def voice_status(
    _auth: ChatAuthIdentity = Depends(require_chat_scope(Scope.CHAT)),
) -> Dict[str, Any]:
    """Whether chat-ui should show the microphone button, and its limits."""
    return {
        "enabled": _enabled(),
        "mode": "remote" if is_remote_stt_enabled() else "local",
        "max_duration_sec": _max_seconds(),
        "max_bytes": _max_bytes(),
    }


@router.post("/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: str = Form(""),
    auth: ChatAuthIdentity = Depends(require_chat_scope(Scope.CHAT)),
) -> Dict[str, Any]:
    """Transcribe one dictation recording and return its text."""
    if not _enabled():
        raise HTTPException(status_code=503, detail="voice_input_disabled")

    limit = _max_bytes()
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="too_large")
    if not data:
        raise HTTPException(status_code=422, detail="empty")

    mime = (file.content_type or "").split(";")[0].strip().lower()
    suffix = _EXTENSIONS.get(mime) or Path(file.filename or "").suffix or ".webm"
    engine = build_engine_from_env()

    with tempfile.TemporaryDirectory(prefix="aion-voice-") as tmp:
        src = Path(tmp) / f"dictation{suffix}"
        src.write_bytes(data)
        # Shared with WhatsApp voice notes: one job at a time on the engine.
        async with STT_JOB_LOCK:
            result = await transcribe_audio_to_text(
                src,
                engine=engine,
                language=resolve_language(language),
                max_duration_sec=_max_seconds(),
            )

    if not result.get("ok"):
        code = str(result.get("error") or "transcribe_failed")
        logger.info(
            "voice_transcribe_failed user=%s error=%s",
            auth.identifier or "anonymous",
            code,
        )
        raise HTTPException(status_code=_ERROR_STATUS.get(code, 500), detail=code)

    logger.info(
        "voice_transcribe_ok user=%s engine=%s duration_sec=%s chars=%d",
        auth.identifier or "anonymous",
        result.get("engine"),
        result.get("duration_sec"),
        len(result.get("text") or ""),
    )
    return {
        "text": result["text"],
        "language": result.get("language"),
        "duration_sec": result.get("duration_sec"),
    }
