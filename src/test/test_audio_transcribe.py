"""Deterministic coverage for src.tools.audio_transcribe (stt MCP server core).

No model and no STT service are needed: audio fixtures are synthesised (sine
waves written with ``wave`` or encoded with PyAV) and engines are faked, so the
tests exercise decoding, chunking, budget/resume and the two engine adapters.
"""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

pytest.importorskip("av")

from src.tools import audio_transcribe as at  # noqa: E402
from src.tools.audio_transcribe import (  # noqa: E402
    SAMPLE_RATE,
    ChunkResult,
    SttEngine,
    build_engine_from_env,
    is_remote_stt_enabled,
    iter_audio_chunks,
    probe_audio_duration,
    resolve_language,
    transcribe_audio_file,
)

_STT_ENV = (
    "AION_STT_BASE_URL",
    "AION_STT_API_KEY",
    "AION_STT_MODEL",
    "AION_STT_LANGUAGE",
    "AION_STT_CHUNK_SEC",
    "AION_STT_LOCAL_CHUNK_SEC",
    "AION_STT_MAX_AUDIO_BYTES",
    "AION_STT_MAX_DURATION_SEC",
    "AION_STT_INLINE_MAX_CHARS",
)


@pytest.fixture(autouse=True)
def _clean_stt_env(monkeypatch):
    """Isolate every test from STT settings in the developer's shell/.env."""
    for name in _STT_ENV:
        monkeypatch.delenv(name, raising=False)


def _write_wav(
    path: Path, seconds: float, rate: int = 44100, channels: int = 2
) -> Path:
    """Stereo 440 Hz sine at 44.1 kHz: forces both downmix and resampling."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    mono = (0.3 * np.sin(2 * math.pi * 440 * t) * 32767).astype("<i2")
    frames = np.repeat(mono, channels)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())
    return path


def _encode_with_pyav(path: Path, codec: str, seconds: float, rate: int) -> Path:
    """Encode a mono sine with PyAV (mp3 / opus), the formats users actually upload."""
    import av

    container = av.open(str(path), mode="w")
    stream = container.add_stream(codec, rate=rate)
    stream.layout = "mono"
    total = int(seconds * rate)
    step = 960
    for offset in range(0, total, step):
        n = min(step, total - offset)
        t = (np.arange(n) + offset) / rate
        samples = (0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="flt", layout="mono"
        )
        frame.sample_rate = rate
        frame.pts = offset
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return path


def _fake_engine(
    chunk_sec: float = 4.0, *, calls: list | None = None, on_call=None
) -> SttEngine:
    """Engine returning one segment per chunk that encodes the chunk length."""

    async def transcribe_chunk(pcm: np.ndarray, language):
        if calls is not None:
            calls.append((pcm.size, language))
        if on_call is not None:
            on_call()
        secs = pcm.size / SAMPLE_RATE
        return ChunkResult(
            segments=[(0.5, secs, f"parlato {secs:.0f}s")], language="it"
        )

    return SttEngine(
        name="fake",
        model="fake-1",
        chunk_sec=chunk_sec,
        transcribe_chunk=transcribe_chunk,
    )


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def test_remote_mode_requires_url_and_real_key(monkeypatch):
    """Same rule as OCR: URL + key, and the EMPTY placeholder means local."""
    assert not is_remote_stt_enabled()
    monkeypatch.setenv("AION_STT_BASE_URL", "http://stt:8000/v1")
    assert not is_remote_stt_enabled()
    monkeypatch.setenv("AION_STT_API_KEY", "EMPTY")
    assert not is_remote_stt_enabled()
    monkeypatch.setenv("AION_STT_API_KEY", "sk-test")
    assert is_remote_stt_enabled()
    assert build_engine_from_env().name == "remote"


def test_local_engine_is_default(monkeypatch):
    """Without a remote service the local faster-whisper engine is selected."""
    engine = build_engine_from_env()
    assert engine.name == "local"
    assert engine.model == "small"
    assert engine.chunk_sec == 60.0


def test_resolve_language_defaults_and_auto(monkeypatch):
    """Empty -> AION_STT_LANGUAGE (default it); 'auto' at any level -> detect."""
    assert resolve_language("") == "it"
    assert resolve_language("EN") == "en"
    assert resolve_language("auto") is None
    monkeypatch.setenv("AION_STT_LANGUAGE", "auto")
    assert resolve_language("") is None


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def test_iter_chunks_resamples_and_splits(tmp_path):
    """10 s of 44.1 kHz stereo -> 16 kHz mono chunks of 4 s, 4 s, 2 s."""
    src = _write_wav(tmp_path / "tone.wav", 10.0)
    chunks = list(iter_audio_chunks(src, start_sec=0.0, chunk_sec=4.0))
    assert [round(s, 3) for s, _ in chunks] == [0.0, 4.0, 8.0]
    sizes = [pcm.size for _, pcm in chunks]
    assert sizes[:2] == [4 * SAMPLE_RATE, 4 * SAMPLE_RATE]
    assert abs(sizes[2] - 2 * SAMPLE_RATE) <= 160  # resampler rounding (<10 ms)
    assert all(pcm.dtype == np.float32 for _, pcm in chunks)
    assert 0.2 < float(np.abs(chunks[0][1]).max()) <= 0.31


def test_iter_chunks_honours_start_and_end(tmp_path):
    """Seek + trim: start at 5 s, stop at 8 s -> exactly 3 s of audio."""
    src = _write_wav(tmp_path / "tone.wav", 10.0)
    chunks = list(iter_audio_chunks(src, start_sec=5.0, chunk_sec=2.0, end_sec=8.0))
    assert [round(s, 3) for s, _ in chunks] == [5.0, 7.0]
    total = sum(pcm.size for _, pcm in chunks)
    assert abs(total - 3 * SAMPLE_RATE) <= 160


@pytest.mark.parametrize(
    ("name", "codec", "rate"),
    [("nota.mp3", "mp3", 44100), ("vocale.ogg", "libopus", 48000)],
)
def test_compressed_formats_decode(tmp_path, name, codec, rate):
    """mp3 uploads and Ogg/Opus voice notes decode through PyAV's bundled FFmpeg."""
    import av

    try:
        av.codec.Codec(codec, "w")
    except Exception:  # noqa: BLE001 - encoder not in this PyAV build
        pytest.skip(f"{codec} encoder unavailable")
    src = _encode_with_pyav(tmp_path / name, codec, 6.0, rate)
    duration = probe_audio_duration(src)
    assert duration is None or abs(duration - 6.0) < 0.2
    total = sum(
        pcm.size for _, pcm in iter_audio_chunks(src, start_sec=0.0, chunk_sec=4.0)
    )
    assert abs(total / SAMPLE_RATE - 6.0) < 0.2


# ---------------------------------------------------------------------------
# Chunk loop, artefacts, resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcribe_writes_chunks_transcript_and_manifest(tmp_path):
    """Happy path: per-chunk files, absolute [mm:ss] stamps, inline text."""
    src = _write_wav(tmp_path / "a1b2c3d4_Riunione Lunedi.wav", 10.0)
    session = tmp_path / "session"
    result = await transcribe_audio_file(
        src, session, engine=_fake_engine(), language="it"
    )

    assert result["ok"] is True
    assert result["slug"] == "riunione_lunedi"
    assert result["engine"] == "fake" and result["model"] == "fake-1"
    assert result["chunks_written"] == 3
    assert result["partial"] is False
    root = session / "derived/audio/riunione_lunedi"
    assert sorted(p.name for p in (root / "chunks").iterdir()) == [
        "c0000.txt",
        "c0001.txt",
        "c0002.txt",
    ]
    transcript = (root / "transcript.txt").read_text(encoding="utf-8").splitlines()
    assert transcript == [
        "[00:00] parlato 4s",
        "[00:04] parlato 4s",
        "[00:08] parlato 2s",
    ]
    assert result["text"].startswith("[00:00] parlato 4s")
    assert result["transcript_path"] == "derived/audio/riunione_lunedi/transcript.txt"
    on_disk = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert "text" not in on_disk and on_disk["chunk_sec"] == 4.0


@pytest.mark.asyncio
async def test_second_call_reuses_existing_chunks(tmp_path):
    """Idempotence: a repeated call transcribes nothing and returns the same text."""
    src = _write_wav(tmp_path / "memo.wav", 10.0)
    session = tmp_path / "session"
    await transcribe_audio_file(src, session, engine=_fake_engine())
    calls: list = []
    again = await transcribe_audio_file(src, session, engine=_fake_engine(calls=calls))
    assert calls == []
    assert again["chunks_skipped_existing"] == 3
    assert again["chars"] > 0


@pytest.mark.asyncio
async def test_budget_returns_partial_and_resume_completes(tmp_path):
    """A slow engine hits the budget; resuming from resume_from_sec finishes the job."""
    src = _write_wav(tmp_path / "lungo.wav", 10.0)
    session = tmp_path / "session"
    now = {"t": 0.0}

    def tick():
        now["t"] += 50.0  # every chunk "takes" 50 s

    first = await transcribe_audio_file(
        src,
        session,
        engine=_fake_engine(on_call=tick),
        budget_sec=60.0,
        clock=lambda: now["t"],
    )
    assert first["partial"] is True
    assert first["chunks_written"] == 1
    assert first["resume_from_sec"] == 4.0
    assert "start_sec=4" in first["next_step"]

    second = await transcribe_audio_file(
        src, session, engine=_fake_engine(), start_sec=first["resume_from_sec"]
    )
    assert second["partial"] is False
    assert second["chunks_written"] == 2
    assert second["text"].count("parlato") == 3


@pytest.mark.asyncio
async def test_chunk_size_change_restarts_from_scratch(tmp_path):
    """Switching engine (different chunk length) must not mix misaligned chunk files."""
    src = _write_wav(tmp_path / "memo.wav", 10.0)
    session = tmp_path / "session"
    await transcribe_audio_file(src, session, engine=_fake_engine(chunk_sec=4.0))
    result = await transcribe_audio_file(
        src, session, engine=_fake_engine(chunk_sec=5.0)
    )
    assert result["chunks_written"] == 2
    files = sorted(p.name for p in (session / "derived/audio/memo/chunks").iterdir())
    assert files == ["c0000.txt", "c0001.txt"]


@pytest.mark.asyncio
async def test_max_duration_limits_the_window(tmp_path):
    """start_sec/max_duration_sec transcribe only the requested window."""
    src = _write_wav(tmp_path / "memo.wav", 10.0)
    calls: list = []
    result = await transcribe_audio_file(
        src,
        tmp_path / "s",
        engine=_fake_engine(calls=calls),
        start_sec=4.0,
        max_duration_sec=4.0,
    )
    assert len(calls) == 1
    assert result["transcribed_until_sec"] == 8.0
    assert result["text"] == "[00:04] parlato 4s"


@pytest.mark.asyncio
async def test_non_audio_and_limits_are_reported(tmp_path, monkeypatch):
    """Clear JSON errors instead of exceptions: wrong file type, too big, too long."""
    txt = tmp_path / "note.txt"
    txt.write_text("not audio", encoding="utf-8")
    res = await transcribe_audio_file(txt, tmp_path / "s", engine=_fake_engine())
    assert res["ok"] is False and res["error"] == "not_audio"
    assert "ocr_file" in res["hint"]

    src = _write_wav(tmp_path / "memo.wav", 3.0)
    monkeypatch.setenv("AION_STT_MAX_AUDIO_BYTES", "100")
    res = await transcribe_audio_file(src, tmp_path / "s", engine=_fake_engine())
    assert res["error"] == "too_large"

    monkeypatch.delenv("AION_STT_MAX_AUDIO_BYTES")
    monkeypatch.setenv("AION_STT_MAX_DURATION_SEC", "2")
    res = await transcribe_audio_file(src, tmp_path / "s", engine=_fake_engine())
    assert res["error"] == "too_long"


@pytest.mark.asyncio
async def test_first_chunk_failure_fails_fast(tmp_path):
    """A broken engine/model surfaces as engine_failed with an operator hint."""

    async def boom(pcm, language):
        raise RuntimeError("model missing")

    engine = SttEngine(
        name="local", model="small", chunk_sec=4.0, transcribe_chunk=boom
    )
    src = _write_wav(tmp_path / "memo.wav", 6.0)
    res = await transcribe_audio_file(src, tmp_path / "s", engine=engine)
    assert res["ok"] is False and res["error"] == "engine_failed"
    assert "AION_STT_LOCAL_MODEL" in res["hint"]


@pytest.mark.asyncio
async def test_long_transcript_returns_excerpt_only(tmp_path, monkeypatch):
    """Above AION_STT_INLINE_MAX_CHARS the agent gets an excerpt plus grep_hint."""
    monkeypatch.setenv("AION_STT_INLINE_MAX_CHARS", "10")
    src = _write_wav(tmp_path / "memo.wav", 10.0)
    res = await transcribe_audio_file(src, tmp_path / "s", engine=_fake_engine())
    assert "text" not in res
    assert res["excerpt"].startswith("[00:00]")
    assert "audio/memo/chunks" in res["grep_hint"]


# ---------------------------------------------------------------------------
# Engine adapters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_engine_posts_openai_multipart(tmp_path, monkeypatch):
    """Remote engine: multipart WAV + model + language to /audio/transcriptions."""
    monkeypatch.setenv("AION_STT_BASE_URL", "http://stt.test/v1/")
    monkeypatch.setenv("AION_STT_API_KEY", "sk-test")
    monkeypatch.setenv("AION_STT_MODEL", "whisper-x")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": " Buongiorno a tutti. "})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        engine = build_engine_from_env(client)
        assert engine.chunk_sec == 30.0
        src = _write_wav(tmp_path / "memo.wav", 3.0)
        res = await transcribe_audio_file(
            src, tmp_path / "s", engine=engine, language="it"
        )

    assert (
        res["ok"] is True and res["engine"] == "remote" and res["model"] == "whisper-x"
    )
    assert res["text"] == "[00:00] Buongiorno a tutti."
    req = seen[0]
    assert str(req.url) == "http://stt.test/v1/audio/transcriptions"
    assert req.headers["Authorization"] == "Bearer sk-test"
    body = req.read()
    assert b'name="model"' in body and b"whisper-x" in body
    assert b'name="language"' in body and b"RIFF" in body


@pytest.mark.asyncio
async def test_remote_engine_http_error_is_reported(tmp_path, monkeypatch):
    """A 500 from the service becomes engine_failed carrying the HTTP status."""
    monkeypatch.setenv("AION_STT_BASE_URL", "http://stt.test/v1")
    monkeypatch.setenv("AION_STT_API_KEY", "sk-test")
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="GPU on fire"))
    async with httpx.AsyncClient(transport=transport) as client:
        res = await transcribe_audio_file(
            _write_wav(tmp_path / "memo.wav", 3.0),
            tmp_path / "s",
            engine=build_engine_from_env(client),
        )
    assert res["error"] == "engine_failed"
    assert "HTTP 500" in res["message"]
    assert "AION_STT_BASE_URL" in res["hint"]


@pytest.mark.asyncio
async def test_local_engine_maps_whisper_segments(tmp_path, monkeypatch):
    """Local engine: faster-whisper segments shifted by the chunk offset; VAD on."""
    captured: dict = {}

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            segs = [
                SimpleNamespace(start=0.0, end=1.5, text=" Primo punto."),
                SimpleNamespace(start=2.0, end=3.0, text="   "),  # blank -> dropped
            ]
            return iter(segs), SimpleNamespace(language="it", language_probability=0.97)

    monkeypatch.setattr(at, "_load_local_model", lambda *a, **k: FakeModel())
    monkeypatch.setenv("AION_STT_LOCAL_CHUNK_SEC", "5")
    engine = build_engine_from_env()
    res = await transcribe_audio_file(
        _write_wav(tmp_path / "memo.wav", 8.0),
        tmp_path / "s",
        engine=engine,
        language=None,
    )

    assert captured["vad_filter"] is True and captured["language"] is None
    assert res["text"].splitlines() == ["[00:00] Primo punto.", "[00:05] Primo punto."]
    assert res["language_detected"] == "it" and res["language_probability"] == 0.97


# ---------------------------------------------------------------------------
# Runtime wiring
# ---------------------------------------------------------------------------


def test_stt_is_session_scoped_and_a_known_cold_tool():
    """stt reads AION_CHAT_SESSION_ID, and tool_search must warm it by tool name."""
    from src.mcp_manager import _session_scoped_servers
    from src.runtime.tool_exposure import _KNOWN_COLD_TOOLS

    assert "stt" in _session_scoped_servers()
    assert _KNOWN_COLD_TOOLS["transcribe_audio"] == "stt"


def test_timeout_message_for_transcribe_audio_explains_resume():
    """A transcription timeout points at resume, not at SQL or doc_ingest."""
    from src.runtime.mcp_tool_result import build_timeout_message

    msg = build_timeout_message("stt", "stt-transcribe_audio")
    assert "transcribe_audio" in msg and "resume_from_sec" in msg
    assert "PostgreSQL" not in msg and "doc_ingest" not in msg
