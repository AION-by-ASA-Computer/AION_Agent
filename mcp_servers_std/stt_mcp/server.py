"""
MCP STT: speech-to-text of audio files in the chat session (audio twin of ocr_mcp).

Engine selection mirrors the OCR server: an OpenAI-compatible
``/audio/transcriptions`` service when ``AION_STT_BASE_URL`` and
``AION_STT_API_KEY`` are set, local faster-whisper (CPU, int8) otherwise.
The chunking/resume logic lives in ``src/tools/audio_transcribe.py`` so other
callers can reuse it without MCP.

Requires AION_CHAT_SESSION_ID (set by the MCP pool: this server is session-scoped).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

mcp = FastMCP("AION STT")

logger = logging.getLogger("mcp_stt")
logging.basicConfig(level=logging.INFO)

# One transcription at a time per worker: the local model is CPU-bound (two
# concurrent runs would only halve each other's speed and double peak RAM) and
# the remote service is usually a single shared GPU, like the OCR one.
_stt_lock = asyncio.Lock()


def _require_session() -> str:
    sid = os.environ.get("AION_CHAT_SESSION_ID", "").strip()
    if not sid:
        logger.error("AION_CHAT_SESSION_ID not set")
        raise RuntimeError("AION_CHAT_SESSION_ID not set")
    return sid


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name, "").strip()
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _clamp_budget(requested: float) -> float:
    """Keep the internal deadline safely below the MCP bridge timeout."""
    bridge = _env_float("AION_MCP_TOOL_RESULT_TIMEOUT", 120.0)
    ceiling = max(10.0, bridge - 25.0)
    try:
        value = float(requested)
    except (TypeError, ValueError):
        value = 90.0
    if value <= 0:
        value = ceiling
    return min(max(value, 10.0), ceiling)


@mcp.tool()
async def transcribe_audio(
    relative_path: str,
    language: str = "",
    start_sec: float = 0.0,
    max_duration_sec: float = 0.0,
    budget_sec: float = 90.0,
    force: bool = False,
) -> str:
    """
    Transcribe speech from a session audio file (uploads/, derived/, workspace/).

    Accepts any common audio format (mp3, wav, ogg/opus voice notes, m4a, flac,
    webm) and videos with an audio track. The transcript is written to
    ``derived/audio/<slug>/transcript.txt`` (one ``[mm:ss] text`` line per
    segment) and to per-chunk files for grep.

    ``language``: ISO code such as ``it`` or ``en``; empty uses the server default
    (AION_STT_LANGUAGE), ``auto`` detects it. Long recordings are processed in
    chunks within ``budget_sec``: if the result has ``partial: true``, call again
    with ``start_sec=resume_from_sec`` — chunks already transcribed are skipped.
    ``max_duration_sec`` limits the window after ``start_sec`` (0 = until the end);
    ``force`` re-transcribes everything.

    Returns a JSON manifest; the full ``text`` is included when short, otherwise an
    ``excerpt`` plus ``transcript_path`` and ``grep_hint``.
    """
    from src.session_workspace import ensure_session_dirs, safe_resolve, session_root
    from src.tools.audio_transcribe import (
        build_engine_from_env,
        resolve_language,
        transcribe_audio_file,
    )

    sid = _require_session()
    ensure_session_dirs(sid)
    logger.info("STT request for %s in session %s", relative_path, sid)
    try:
        path = safe_resolve(sid, relative_path, must_exist=True)
    except Exception as e:
        return json.dumps(
            {
                "ok": False,
                "error": "path_error",
                "message": str(e),
                "hint": "Call sandbox_list_files(subdir='uploads') to list uploaded files.",
            },
            ensure_ascii=False,
        )

    engine = build_engine_from_env()
    logger.info("STT engine=%s model=%s", engine.name, engine.model)

    async with _stt_lock:
        try:
            manifest = await transcribe_audio_file(
                path,
                session_root(sid),
                engine=engine,
                language=resolve_language(language),
                start_sec=start_sec,
                max_duration_sec=max_duration_sec,
                budget_sec=_clamp_budget(budget_sec),
                force=force,
            )
        except Exception as e:
            logger.exception("transcribe_audio failed for %s", relative_path)
            return json.dumps(
                {"ok": False, "error": "transcribe_failed", "message": str(e)},
                ensure_ascii=False,
            )
    return json.dumps(manifest, ensure_ascii=False)


if __name__ == "__main__":
    import traceback

    from mcp.server.stdio import stdio_server

    async def main():
        try:
            async with stdio_server() as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )
        except Exception as e:
            log = os.path.join("data", "mcp_debug.log")
            os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n--- STT MCP CRASH ---\n{traceback.format_exc()}\n")
            raise e

    asyncio.run(main())
