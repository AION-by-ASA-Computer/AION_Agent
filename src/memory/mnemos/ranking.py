"""Ranking helpers for Mnemos recall (RRF + recency + importance)."""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from src.data.models import LtmNote

from .embedding import reciprocal_rank_fusion


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def rank_half_life_days() -> float:
    return max(1.0, _env_float("AION_MNEMOS_RANK_HALF_LIFE_DAYS", 90.0))


def rank_w_recency() -> float:
    return _env_float("AION_MNEMOS_RANK_W_RECENCY", 0.3)


def rank_w_importance() -> float:
    return _env_float("AION_MNEMOS_RANK_W_IMPORTANCE", 0.2)


def _note_age_days(note: LtmNote, now: datetime) -> float:
    created = note.created_at
    if created is None:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = now - created.astimezone(timezone.utc)
    return max(0.0, delta.total_seconds() / 86400.0)


def final_rank_score(
    note: LtmNote,
    *,
    base_score: float,
    now: Optional[datetime] = None,
) -> float:
    """Combine RRF base with recency and importance boosts."""
    now = now or datetime.now(timezone.utc)
    age = _note_age_days(note, now)
    recency = math.exp(-age / rank_half_life_days())
    imp = max(1, min(5, int(note.importance or 3)))
    imp_norm = (imp - 1) / 4.0
    return base_score * (
        1.0 + rank_w_recency() * recency + rank_w_importance() * imp_norm
    )


def rank_notes(
    ranked_lists: Sequence[Sequence[int]],
    notes_by_id: Dict[int, LtmNote],
    *,
    limit: int,
    now: Optional[datetime] = None,
) -> List[LtmNote]:
    """Merge ranked id lists with RRF, apply recency/importance, return top notes."""
    if not notes_by_id:
        return []
    fused = reciprocal_rank_fusion([list(lst) for lst in ranked_lists if lst])
    if not fused:
        return []

    scored: List[Tuple[float, LtmNote]] = []
    for note_id, base in fused:
        note = notes_by_id.get(note_id)
        if note is None:
            continue
        scored.append((final_rank_score(note, base_score=base, now=now), note))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in scored[:limit]]
