"""Pre-download Chroma default ONNX embeddings (MemPalace / LTM).

First mempalace tool call otherwise downloads ~80MB from S3 inside the MCP
stdio worker, which can exceed ``AION_NO_PROGRESS_TIMEOUT_SEC`` and abort SSE.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from src.session_workspace import data_root

logger = logging.getLogger("aion.mempalace_warmup")

_WARMUP_LOCK = threading.Lock()
_WARMUP_DONE = False


def chroma_embedding_cache_dir() -> Path:
    """Directory shared across users for Chroma ONNX model cache."""
    explicit = (os.environ.get("AION_CHROMA_EMBEDDING_CACHE_DIR") or "").strip()
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else (data_root() / p)
    return data_root() / "chroma_embedding_cache"


def warmup_enabled() -> bool:
    return os.environ.get("AION_MEMPALACE_WARMUP", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def shared_embedding_cache_enabled() -> bool:
    return os.environ.get("AION_CHROMA_SHARED_EMBEDDING_CACHE", "1").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def apply_shared_embedding_cache_env(env: dict[str, str]) -> None:
    """Point Chroma ONNX cache at a shared volume (per MCP subprocess env)."""
    if not shared_embedding_cache_enabled():
        return
    cache = chroma_embedding_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    env["XDG_CACHE_HOME"] = str(cache)
    env.setdefault("TQDM_DISABLE", "1")
    env.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def warmup_chroma_embeddings(*, force: bool = False) -> bool:
    """
    Download / load Chroma ``DefaultEmbeddingFunction`` once.

    Returns True if warmup succeeded or was already done.
    """
    global _WARMUP_DONE
    if not warmup_enabled() and not force:
        return False
    with _WARMUP_LOCK:
        if _WARMUP_DONE and not force:
            return True
        cache = chroma_embedding_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        prev_xdg = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = str(cache)
        os.environ.setdefault("TQDM_DISABLE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        try:
            from chromadb.utils import embedding_functions

            ef = embedding_functions.DefaultEmbeddingFunction()
            ef(["aion-warmup"])
            _WARMUP_DONE = True
            logger.info("Chroma embedding model ready (cache=%s)", cache)
            return True
        except Exception as exc:
            logger.warning("Chroma embedding warmup failed: %s", exc)
            return False
        finally:
            if prev_xdg is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = prev_xdg


def schedule_embedding_warmup() -> None:
    """Fire-and-forget warmup on a daemon thread (FastAPI lifespan)."""
    if not warmup_enabled():
        logger.info("MemPalace embedding warmup disabled (AION_MEMPALACE_WARMUP=0)")
        return

    def _run() -> None:
        warmup_chroma_embeddings()

    threading.Thread(target=_run, name="aion-chroma-warmup", daemon=True).start()
