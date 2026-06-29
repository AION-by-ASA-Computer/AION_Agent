"""Dedup skill candidate via embedding (opzionale)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def compute_similarity(text_a: str, text_b: str) -> float:
    try:
        from src.query_memory import memory as qm

        emb_a = qm.get_embedding(text_a)
        emb_b = qm.get_embedding(text_b)
        if emb_a is None or emb_b is None:
            return 0.0
        na = np.linalg.norm(emb_a)
        nb = np.linalg.norm(emb_b)
        if na < 1e-9 or nb < 1e-9:
            return 0.0
        return float(np.dot(emb_a, emb_b) / (na * nb))
    except Exception:
        return 0.0


def find_similar_skill(description: str, threshold: float = 0.88) -> Optional[Tuple[str, float]]:
    from src.skill_registry import skill_registry

    try:
        from src.query_memory import memory as qm

        target = qm.get_embedding(description)
        if target is None:
            return None
        nt = np.linalg.norm(target)
        if nt < 1e-9:
            return None
        best: Optional[Tuple[str, float]] = None
        for meta in skill_registry.list_summaries(include_draft=True):
            cand_text = f"{meta['name']}: {meta.get('description', '')}"
            cand_emb = qm.get_embedding(cand_text)
            if cand_emb is None:
                continue
            nc = np.linalg.norm(cand_emb)
            if nc < 1e-9:
                continue
            score = float(np.dot(target, cand_emb) / (nt * nc))
            if score >= threshold and (best is None or score > best[1]):
                best = (meta["name"], score)
        return best
    except Exception:
        return None
