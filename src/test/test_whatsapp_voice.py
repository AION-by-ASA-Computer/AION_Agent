"""``channels.whatsapp.voice``: transcription of WhatsApp voice notes.

Runs the real ``transcribe_audio_file`` (the stt MCP server core) on a
synthetic wav stored in a temporary ``AION_DATA_DIR``, with a fake engine in
place of Whisper, so the tests cover the mapping from the STT manifest to the
``VoiceTranscript`` the dispatcher uses.
"""

from __future__ import annotations

import io
import math
import wave

import numpy as np
import pytest

pytest.importorskip("av")

from src.channels.whatsapp import voice  # noqa: E402
from src.session_workspace import save_upload, session_root  # noqa: E402
from src.tools import audio_transcribe as at  # noqa: E402
from src.tools.audio_transcribe import SAMPLE_RATE, ChunkResult, SttEngine  # noqa: E402

CID = "conv-voice-1"


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    """Isolated session storage and no STT/voice settings from the developer's env."""
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    for name in (
        "AION_STT_LANGUAGE",
        "AION_STT_INLINE_MAX_CHARS",
        "AION_STT_MAX_DURATION_SEC",
        "AION_WHATSAPP_VOICE",
        "AION_WHATSAPP_VOICE_MAX_SEC",
        "AION_WHATSAPP_VOICE_BUDGET_SEC",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _wav_bytes(seconds: float) -> bytes:
    """Mono 16 kHz 440 Hz sine: a decodable stand-in for a voice note."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    pcm = (0.3 * np.sin(2 * math.pi * 440 * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _use_engine(monkeypatch, *segments: str, fail: bool = False, calls=None):
    """Make ``build_engine_from_env`` return a fake engine.

    Each chunk yields ``segments`` (empty = silence); ``fail`` raises like an
    unreachable STT service.
    """

    async def transcribe_chunk(pcm, language):
        if calls is not None:
            calls.append(language)
        if fail:
            raise RuntimeError("connection refused")
        secs = pcm.size / SAMPLE_RATE
        return ChunkResult(segments=[(0.0, secs, s) for s in segments], language="it")

    engine = SttEngine(
        name="fake", model="fake-1", chunk_sec=30.0, transcribe_chunk=transcribe_chunk
    )
    monkeypatch.setattr(at, "build_engine_from_env", lambda client=None: engine)


def _store(seconds: float = 3.0) -> dict:
    return save_upload(CID, "vocale_20261030_101500.wav", _wav_bytes(seconds))


def test_voice_enabled_kill_switch(monkeypatch):
    """``AION_WHATSAPP_VOICE`` defaults to on and accepts the usual false values."""
    monkeypatch.delenv("AION_WHATSAPP_VOICE", raising=False)
    assert voice.voice_enabled()
    monkeypatch.setenv("AION_WHATSAPP_VOICE", "off")
    assert not voice.voice_enabled()


def test_plain_text_drops_timestamps():
    """Transcript lines become one paragraph without ``[mm:ss]`` prefixes."""
    raw = "[00:00] Ciao, mi servono\n\n[00:31] gli ordini di ieri\n[1:00:02] grazie"
    assert voice._plain_text(raw) == "Ciao, mi servono gli ordini di ieri grazie"


@pytest.mark.anyio
async def test_transcribes_with_default_language_and_writes_artefacts(
    data_dir, monkeypatch
):
    """Success: plain text, server-default language, usual derived/audio output."""
    calls: list = []
    _use_engine(monkeypatch, "Quanti ordini", "abbiamo ieri?", calls=calls)
    att = _store()

    result = await voice.transcribe_voice_note(CID, att)

    assert result.error is None and not result.partial
    assert result.text == "Quanti ordini abbiamo ieri?"
    assert result.duration_sec == pytest.approx(3.0, abs=0.1)
    assert calls == ["it"]  # AION_STT_LANGUAGE default
    # The slug comes from the unique upload name, as the pipeline hint expects.
    manifest = at.load_audio_manifest(session_root(CID), att["name"])
    assert manifest and manifest["ok"] and not manifest["partial"]


@pytest.mark.anyio
async def test_long_transcript_is_read_from_file(data_dir, monkeypatch):
    """Above AION_STT_INLINE_MAX_CHARS the text comes from transcript.txt."""
    monkeypatch.setenv("AION_STT_INLINE_MAX_CHARS", "5")
    _use_engine(monkeypatch, "una frase piuttosto lunga")

    result = await voice.transcribe_voice_note(CID, _store())

    assert result.text == "una frase piuttosto lunga"


@pytest.mark.anyio
async def test_too_long_is_rejected_before_transcribing(data_dir, monkeypatch):
    """Audio over AION_WHATSAPP_VOICE_MAX_SEC is refused, not truncated."""
    monkeypatch.setenv("AION_WHATSAPP_VOICE_MAX_SEC", "2")
    calls: list = []
    _use_engine(monkeypatch, "mai", calls=calls)

    result = await voice.transcribe_voice_note(CID, _store(seconds=3.0))

    assert result.error == "too_long"
    assert calls == []


@pytest.mark.anyio
async def test_silence_is_no_speech(data_dir, monkeypatch):
    _use_engine(monkeypatch)  # no segments

    result = await voice.transcribe_voice_note(CID, _store())

    assert result.error == "no_speech" and result.text == ""


@pytest.mark.anyio
async def test_engine_failure_is_reported(data_dir, monkeypatch):
    """An unusable engine surfaces the STT error code instead of raising."""
    _use_engine(monkeypatch, fail=True)

    result = await voice.transcribe_voice_note(CID, _store())

    assert result.error == "engine_failed"


@pytest.mark.anyio
async def test_missing_file_is_a_failure(data_dir, monkeypatch):
    _use_engine(monkeypatch, "mai")

    result = await voice.transcribe_voice_note(
        CID, {"relative_path": "uploads/non_esiste.ogg"}
    )

    assert result.error == "transcribe_failed"
