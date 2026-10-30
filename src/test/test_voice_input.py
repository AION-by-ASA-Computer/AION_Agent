"""Tests for chat-ui dictation: ``transcribe_audio_to_text`` and ``/v1/voice/*``.

Same approach as ``test_audio_transcribe.py``: audio is a synthesised sine wave
and the engine is faked, so no model or STT service is needed. The router is
mounted on a bare FastAPI app with chat auth stubbed out.
"""

from __future__ import annotations

import asyncio
import math
import tempfile
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

pytest.importorskip("av")

from src.api import auth_login  # noqa: E402
from src.api.auth_login import ChatAuthIdentity  # noqa: E402
from src.api.v1 import voice  # noqa: E402
from src.tools.audio_transcribe import (  # noqa: E402
    ChunkResult,
    SttEngine,
    transcribe_audio_to_text,
)

_ENV = (
    "AION_CHAT_VOICE_INPUT",
    "AION_STT_DICTATION_MAX_SEC",
    "AION_STT_DICTATION_MAX_BYTES",
    "AION_STT_BASE_URL",
    "AION_STT_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _write_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    n = int(seconds * rate)
    t = np.arange(n) / rate
    samples = (0.3 * np.sin(2 * math.pi * 440 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def _fake_engine(
    texts: list[str] | None = None, chunk_sec: float = 2.0, fail: bool = False
) -> tuple[SttEngine, list[float]]:
    """Engine returning ``texts`` in order (one per chunk); records chunk lengths."""
    seen: list[float] = []
    queue = list(texts or [])

    async def transcribe_chunk(pcm, language):
        if fail:
            raise RuntimeError("service down")
        seen.append(pcm.size / 16000)
        text = queue.pop(0) if queue else ""
        return ChunkResult(segments=[(0.0, 1.0, text)] if text else [], language="it")

    return SttEngine("fake", "fake-model", chunk_sec, transcribe_chunk), seen


# ---------------------------------------------------------------------------
# transcribe_audio_to_text
# ---------------------------------------------------------------------------


def test_joins_chunks_without_timestamps(tmp_path):
    src = _write_wav(tmp_path / "a.wav", 5.0)
    engine, seen = _fake_engine(["ciao", "come", "stai"])
    out = asyncio.run(transcribe_audio_to_text(src, engine=engine, language="it"))
    assert out["ok"] is True
    assert out["text"] == "ciao come stai"
    assert out["language"] == "it"
    assert out["duration_sec"] == pytest.approx(5.0, abs=0.05)
    assert len(seen) == 3
    assert list(tmp_path.iterdir()) == [src]  # nothing written next to the clip


def test_rejects_clip_longer_than_limit(tmp_path):
    src = _write_wav(tmp_path / "a.wav", 5.0)
    engine, seen = _fake_engine(["x"])
    out = asyncio.run(transcribe_audio_to_text(src, engine=engine, max_duration_sec=3))
    assert out["ok"] is False and out["error"] == "too_long"
    assert seen == []


def test_empty_when_no_speech(tmp_path):
    src = _write_wav(tmp_path / "a.wav", 1.0)
    engine, _ = _fake_engine([])
    out = asyncio.run(transcribe_audio_to_text(src, engine=engine))
    assert out == {"ok": False, "error": "empty", "message": out["message"]}


def test_not_audio(tmp_path):
    src = tmp_path / "a.webm"
    src.write_bytes(b"definitely not audio")
    engine, _ = _fake_engine(["x"])
    out = asyncio.run(transcribe_audio_to_text(src, engine=engine))
    assert out["error"] == "not_audio"


def test_engine_failure(tmp_path):
    src = _write_wav(tmp_path / "a.wav", 1.0)
    engine, _ = _fake_engine(fail=True)
    out = asyncio.run(transcribe_audio_to_text(src, engine=engine))
    assert out["error"] == "engine_failed"


# ---------------------------------------------------------------------------
# /v1/voice router
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    async def _identity(authorization, *args, **kwargs):
        if authorization != "Bearer ok":
            raise HTTPException(status_code=401, detail="auth_required")
        return ChatAuthIdentity(identifier="alice", via="chat_token")

    monkeypatch.setattr(auth_login, "_resolve_chat_identity", _identity)
    monkeypatch.setattr(voice, "_engine_available", lambda: True)
    app = FastAPI()
    app.include_router(voice.router, prefix="/v1")
    with TestClient(app, headers={"Authorization": "Bearer ok"}) as c:
        yield c


def _post(client: TestClient, path: Path, **headers):
    with path.open("rb") as fh:
        return client.post(
            "/v1/voice/transcribe",
            files={"file": ("dictation.wav", fh, "audio/wav")},
            data={"language": "it"},
            headers=headers,
        )


def test_status_reports_limits(client, monkeypatch):
    monkeypatch.setenv("AION_STT_DICTATION_MAX_SEC", "120")
    body = client.get("/v1/voice/status").json()
    assert body["enabled"] is True
    assert body["mode"] == "local"
    assert body["max_duration_sec"] == 120


def test_status_disabled_by_flag_or_missing_engine(client, monkeypatch):
    monkeypatch.setenv("AION_CHAT_VOICE_INPUT", "0")
    assert client.get("/v1/voice/status").json()["enabled"] is False
    monkeypatch.delenv("AION_CHAT_VOICE_INPUT")
    monkeypatch.setattr(voice, "_engine_available", lambda: False)
    assert client.get("/v1/voice/status").json()["enabled"] is False


def test_requires_auth(client, tmp_path):
    src = _write_wav(tmp_path / "a.wav", 1.0)
    assert _post(client, src, Authorization="Bearer nope").status_code == 401


def test_transcribe_returns_text_and_removes_audio(client, monkeypatch, tmp_path):
    engine, _ = _fake_engine(["buongiorno a tutti"])
    monkeypatch.setattr(voice, "build_engine_from_env", lambda: engine)
    created: list[str] = []
    real_tmpdir = tempfile.TemporaryDirectory

    def _tracking_tmpdir(*args, **kwargs):
        tmp = real_tmpdir(*args, **kwargs)
        created.append(tmp.name)
        return tmp

    monkeypatch.setattr(voice.tempfile, "TemporaryDirectory", _tracking_tmpdir)
    r = _post(client, _write_wav(tmp_path / "a.wav", 1.5))
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "buongiorno a tutti"
    assert created and not Path(created[0]).exists()


def test_transcribe_too_large(client, monkeypatch, tmp_path):
    monkeypatch.setenv("AION_STT_DICTATION_MAX_BYTES", "1000")
    r = _post(client, _write_wav(tmp_path / "a.wav", 1.0))
    assert r.status_code == 413
    assert r.json()["detail"] == "too_large"


def test_transcribe_too_long(client, monkeypatch, tmp_path):
    monkeypatch.setenv("AION_STT_DICTATION_MAX_SEC", "2")
    engine, _ = _fake_engine(["x"])
    monkeypatch.setattr(voice, "build_engine_from_env", lambda: engine)
    r = _post(client, _write_wav(tmp_path / "a.wav", 4.0))
    assert r.status_code == 422
    assert r.json()["detail"] == "too_long"


def test_transcribe_disabled(client, monkeypatch, tmp_path):
    monkeypatch.setenv("AION_CHAT_VOICE_INPUT", "0")
    r = _post(client, _write_wav(tmp_path / "a.wav", 1.0))
    assert r.status_code == 503
