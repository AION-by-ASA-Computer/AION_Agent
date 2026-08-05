"""Embedding helpers for Mnemos hybrid recall."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger("aion.memory.mnemos.embedding")


def embedding_recall_enabled() -> bool:
    return os.getenv("AION_MNEMOS_EMBEDDING_RECALL", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def embed_on_bulk_insert() -> bool:
    return os.getenv("AION_MNEMOS_EMBED_ON_BULK", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def embedding_min_score() -> float:
    try:
        return float(os.getenv("AION_MNEMOS_EMBEDDING_MIN_SCORE", "0.25"))
    except ValueError:
        return 0.25


def embedding_scan_limit() -> int:
    try:
        return max(50, int(os.getenv("AION_MNEMOS_EMBEDDING_SCAN_LIMIT", "300")))
    except ValueError:
        return 300


def embeddings_configured() -> bool:
    model = (os.getenv("AION_EMBEDDING_MODEL") or "").strip()
    url = (os.getenv("AION_EMBEDDING_URL") or "").strip()
    return bool(model and url)


def get_embedding(text: str) -> Optional[np.ndarray]:
    from src.query_memory import memory

    return memory.get_embedding(text)


def embedding_to_bytes(vec: Optional[np.ndarray]) -> Optional[bytes]:
    if vec is None:
        return None
    return vec.astype(np.float32).tobytes()


def bytes_to_embedding(blob: Optional[bytes]) -> Optional[np.ndarray]:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


async def maybe_embed_text(text: str) -> Optional[bytes]:
    """Compute and serialize an embedding when recall mode is enabled."""
    if not embedding_recall_enabled() or not embeddings_configured():
        return None
    try:
        vec = await asyncio.to_thread(get_embedding, text)
    except Exception as exc:
        logger.warning("Mnemos embedding fetch failed: %s", exc)
        return None
    return embedding_to_bytes(vec)


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    *,
    k: int = 60,
) -> list[tuple[int, float]]:
    """Merge ranked note-id lists with RRF. Higher score = better."""
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, note_id in enumerate(ranked):
            scores[note_id] = scores.get(note_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)
