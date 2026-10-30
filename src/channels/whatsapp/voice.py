"""Speech-to-text of WhatsApp voice notes before the agent turn.

The dispatcher (``dispatcher._handle_linked``) stores an inbound ``audio``
message in the conversation like any other media, then calls
``transcribe_voice_note`` so the transcript becomes the user's text for the
turn. Transcription reuses ``src.tools.audio_transcribe.transcribe_audio_file``
in-process, i.e. the same engine (remote Whisper or local faster-whisper) and
the same ``AION_STT_*`` settings as the ``stt`` MCP server; the artefacts land
in the session's ``derived/audio/<slug>/``, so a later ``transcribe_audio``
call by the agent on the same file reuses them.

See ``docs/integrations/whatsapp.md`` (Messaggi vocali).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.session_workspace import safe_resolve, session_root

logger = logging.getLogger("aion.whatsapp.voice")

# A voice note is usually under a minute: the cap keeps a forwarded hour-long
# recording from holding the sender's queue (and the CPU) for ages.
DEFAULT_MAX_DURATION_S = 600.0
# No MCP bridge timeout applies here, so one generous run is enough for any
# audio under the duration cap (the turn timeout still bounds the agent part).
DEFAULT_BUDGET_S = 180.0

# ``[mm:ss] `` / ``[h:mm:ss] `` prefixes of the transcript lines.
_TIMESTAMP_RE = re.compile(r"^\[\d+(?::\d{2}){1,2}\]\s*")

# Same reason as ``_stt_lock`` in the stt MCP server: the local model is
# CPU-bound and the remote service usually a single GPU, so one job at a time.
# In-process is enough because the backend runs with ``--workers 1``.
_stt_lock = asyncio.Lock()


@dataclass
class VoiceTranscript:
    """Outcome of a voice-note transcription.

    ``error`` is ``None`` on success, otherwise one of ``too_long``,
    ``no_speech`` or a failure code (``engine_failed``, ``not_audio``, ...),
    which the dispatcher turns into a reply to the user.
    """

    text: str = ""
    partial: bool = False
    error: Optional[str] = None
    duration_sec: Optional[float] = None


def voice_enabled() -> bool:
    """``AION_WHATSAPP_VOICE`` (default on): kill switch for voice notes."""
    raw = (os.getenv("AION_WHATSAPP_VOICE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name) or default))
    except ValueError:
        return default


def max_voice_duration_s() -> float:
    """Longest audio transcribed from WhatsApp (``AION_WHATSAPP_VOICE_MAX_SEC``)."""
    return _env_float("AION_WHATSAPP_VOICE_MAX_SEC", DEFAULT_MAX_DURATION_S, 1.0)


def _budget_s() -> float:
    """Time budget of the transcription (``AION_WHATSAPP_VOICE_BUDGET_SEC``)."""
    return _env_float("AION_WHATSAPP_VOICE_BUDGET_SEC", DEFAULT_BUDGET_S, 10.0)


def _plain_text(transcript: str) -> str:
    """Transcript lines without their timestamps, joined as one paragraph."""
    lines = (_TIMESTAMP_RE.sub("", ln).strip() for ln in transcript.splitlines())
    return " ".join(ln for ln in lines if ln)


async def transcribe_voice_note(
    conversation_id: str, attachment: Dict[str, Any]
) -> VoiceTranscript:
    """Transcribe the stored audio ``attachment`` (``ingest_inbound_media`` output).

    Never raises: failures come back as ``VoiceTranscript.error``. Writes the
    usual STT artefacts under ``derived/audio/<slug>/`` of the conversation.
    """
    from src.tools.audio_transcribe import (
        build_engine_from_env,
        probe_audio_duration,
        resolve_language,
        transcribe_audio_file,
    )

    max_duration = max_voice_duration_s()
    try:
        # The unique upload path (not the alias), so the slug matches the one
        # the pipeline hint and a later transcribe_audio call would use.
        root = session_root(conversation_id)
        path = safe_resolve(
            conversation_id, attachment.get("relative_path", ""), must_exist=True
        )
        # Reject over-long audio up front instead of transcribing only its
        # beginning: a truncated message would silently drop the user's request.
        try:
            duration = await asyncio.to_thread(probe_audio_duration, path)
        except Exception:  # noqa: BLE001 - transcribe_audio_file reports it
            duration = None
        if duration is not None and duration > max_duration:
            return VoiceTranscript(error="too_long", duration_sec=duration)

        engine = build_engine_from_env()
        async with _stt_lock:
            manifest = await transcribe_audio_file(
                path,
                root,
                engine=engine,
                language=resolve_language(""),
                max_duration_sec=max_duration,
                budget_sec=_budget_s(),
            )
    except Exception:  # noqa: BLE001 - reported to the user as a failure
        logger.exception("WhatsApp voice note transcription failed")
        return VoiceTranscript(error="transcribe_failed")

    if not manifest.get("ok"):
        logger.warning(
            "WhatsApp voice note not transcribed: %s %s",
            manifest.get("error"),
            manifest.get("message"),
        )
        return VoiceTranscript(error=str(manifest.get("error") or "transcribe_failed"))

    text = manifest.get("text")
    if text is None:
        # Over AION_STT_INLINE_MAX_CHARS the manifest has only an excerpt.
        try:
            text = (root / manifest["transcript_path"]).read_text(encoding="utf-8")
        except (KeyError, OSError):
            logger.warning("WhatsApp voice note: transcript file unreadable")
            return VoiceTranscript(error="transcribe_failed")
    plain = _plain_text(text)
    duration_sec = manifest.get("duration_sec")
    if not plain:
        return VoiceTranscript(error="no_speech", duration_sec=duration_sec)
    return VoiceTranscript(
        text=plain,
        partial=bool(manifest.get("partial")),
        duration_sec=duration_sec,
    )


__all__ = [
    "VoiceTranscript",
    "max_voice_duration_s",
    "transcribe_voice_note",
    "voice_enabled",
]
