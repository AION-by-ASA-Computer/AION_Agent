"""MemPalace / Chroma embedding warmup helpers."""
from __future__ import annotations

from pathlib import Path

from src.runtime import mempalace_warmup as mw


def test_chroma_embedding_cache_dir_default(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("AION_CHROMA_EMBEDDING_CACHE_DIR", raising=False)
    assert mw.chroma_embedding_cache_dir() == tmp_path / "data" / "chroma_embedding_cache"


def test_apply_shared_embedding_cache_env(monkeypatch):
    monkeypatch.setenv("AION_CHROMA_SHARED_EMBEDDING_CACHE", "1")
    env: dict[str, str] = {"HOME": "/tmp/u"}
    mw.apply_shared_embedding_cache_env(env)
    assert "chroma_embedding_cache" in env["XDG_CACHE_HOME"]
    assert env.get("TQDM_DISABLE") == "1"
