"""Embedding helpers (reuse PromQL QueryMemory HTTP client)."""

from __future__ import annotations

from typing import Optional

import numpy as np


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
