"""Tests for the local STT model admin API (admin-ui → Settings → Audio).

Covers ``src/api/admin_stt.py`` (model status, guarded ahead-of-time download)
and the model lookup helpers in ``src/tools/audio_transcribe.py`` it relies on
(models baked into the image first, then the persistent download directory).
The router is mounted on a bare FastAPI app: admin auth is inherited from the
``/admin`` router in production and is tested elsewhere.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import admin_stt
from src.tools import audio_transcribe as at


def _install(root: Path, name: str) -> Path:
    """Create the minimal on-disk layout that counts as an installed model."""
    model_dir = root / name
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.bin").write_bytes(b"x")
    return model_dir


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Isolated baked/download model dirs, remote STT off, fresh download state."""
    baked = tmp_path / "baked"
    download = tmp_path / "data" / "models" / "faster-whisper"
    baked.mkdir()
    monkeypatch.setenv("AION_STT_LOCAL_MODEL_DIR", str(baked))
    monkeypatch.setattr(at, "local_model_download_dir", lambda: download)
    monkeypatch.delenv("AION_STT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("AION_STT_BASE_URL", raising=False)
    monkeypatch.delenv("AION_STT_API_KEY", raising=False)
    monkeypatch.setattr(admin_stt, "_download", {"model": None, "state": "idle", "error": None})
    monkeypatch.setattr(admin_stt, "_download_task", None)
    return baked, download


@pytest.fixture
def client(dirs):
    """TestClient kept open so background download tasks can finish on its loop."""
    app = FastAPI()
    app.include_router(admin_stt.router, prefix="/admin")
    with TestClient(app) as c:
        yield c


def _wait_for_download(client: TestClient) -> dict:
    """Poll the status endpoint like admin-ui does, until the download ends."""
    for _ in range(100):
        data = client.get("/admin/stt/local-models").json()
        if data["download"]["state"] != "running":
            return data
        time.sleep(0.02)
    raise AssertionError("download did not finish")


def test_search_dirs_put_baked_models_before_downloads(dirs):
    """A model baked into the image wins over a downloaded copy of the same name."""
    baked, download = dirs
    assert at.local_model_search_dirs() == [baked, download]
    _install(download, "small")
    assert at.find_local_model("small") == download / "small"
    _install(baked, "small")
    assert at.find_local_model("small") == baked / "small"


def test_find_local_model_accepts_a_directory_and_reports_missing(dirs, tmp_path):
    """An explicit directory is used as-is; an unknown name means "download needed"."""
    custom = _install(tmp_path, "my-model")
    assert at.find_local_model(str(custom)) == custom
    assert at.find_local_model("medium") is None


def test_status_lists_curated_models_with_install_state(client, dirs):
    """GET reports every curated model, which ones are on disk, and local mode."""
    _, download = dirs
    _install(download, "base")
    data = client.get("/admin/stt/local-models").json()
    assert data["mode"] == "local"
    assert data["current"] == "small"
    assert [m["name"] for m in data["models"]] == list(at.LOCAL_MODEL_CHOICES)
    installed = {m["name"] for m in data["models"] if m["installed"]}
    assert installed == {"base"}
    assert data["download"]["state"] == "idle"


def test_status_keeps_a_hand_set_model_as_custom(client, monkeypatch):
    """A model name set by hand in .env is appended and flagged as custom."""
    monkeypatch.setenv("AION_STT_LOCAL_MODEL", "distil-large-v3")
    data = client.get("/admin/stt/local-models").json()
    assert data["current"] == "distil-large-v3"
    assert data["models"][-1] == {"name": "distil-large-v3", "installed": False, "custom": True}


def test_status_reports_remote_mode(client, monkeypatch):
    """With an external service configured, admin-ui is told the local model is unused."""
    monkeypatch.setenv("AION_STT_BASE_URL", "http://stt.example/v1")
    monkeypatch.setenv("AION_STT_API_KEY", "secret")
    assert client.get("/admin/stt/local-models").json()["mode"] == "remote"


def test_download_rejects_names_outside_the_curated_list(client):
    """Arbitrary Hugging Face repos or paths cannot be fetched through the API."""
    res = client.post("/admin/stt/local-models/..%2Fetc/download")
    assert res.status_code in (400, 404)
    res = client.post("/admin/stt/local-models/distil-large-v3/download")
    assert res.status_code == 400
    assert res.json()["detail"] == "unknown_model"


def test_download_runs_in_background_and_marks_model_installed(client, dirs, monkeypatch):
    """POST starts the download; polling then sees it done and the model installed."""
    _, download = dirs
    calls: list[str] = []

    def fake_download(name: str) -> Path:
        calls.append(name)
        return _install(download, name)

    monkeypatch.setattr(admin_stt, "download_local_model", fake_download)
    res = client.post("/admin/stt/local-models/medium/download")
    assert res.status_code == 200
    data = _wait_for_download(client)
    assert calls == ["medium"]
    assert data["download"] == {"model": "medium", "state": "done", "error": None}
    assert next(m for m in data["models"] if m["name"] == "medium")["installed"] is True


def test_download_failure_is_reported(client, monkeypatch):
    """A failing download ends in state "error" with the reason for admin-ui."""

    def broken(name: str) -> Path:
        raise RuntimeError("disk full")

    monkeypatch.setattr(admin_stt, "download_local_model", broken)
    client.post("/admin/stt/local-models/tiny/download")
    data = _wait_for_download(client)
    assert data["download"]["state"] == "error"
    assert "disk full" in data["download"]["error"]


def test_download_is_skipped_for_installed_models(client, dirs, monkeypatch):
    """Asking for a model already on disk does not start a download."""
    _, download = dirs
    _install(download, "small")
    monkeypatch.setattr(admin_stt, "download_local_model", lambda name: pytest.fail("should not download"))
    data = client.post("/admin/stt/local-models/small/download").json()
    assert data["download"]["state"] == "idle"


def test_second_download_while_one_runs_is_refused(client):
    """Only one download at a time: a concurrent request gets 409."""
    admin_stt._download.update(model="medium", state="running")
    res = client.post("/admin/stt/local-models/tiny/download")
    assert res.status_code == 409
    assert res.json()["detail"] == "download_in_progress"
