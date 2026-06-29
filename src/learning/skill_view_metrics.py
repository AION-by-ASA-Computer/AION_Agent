"""Lightweight skill_view counters (P2.9)."""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict

_METRICS_PATH = Path("data/logs/skill_view_metrics.jsonl")


def _enabled() -> bool:
    return os.getenv("AION_SKILL_VIEW_METRICS", "1").lower() not in ("0", "false", "no")


def record_skill_view(slug: str, user_id: str = "default") -> None:
    if not _enabled() or not (slug or "").strip():
        return
    _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "slug": slug.strip(),
        "user_id": (user_id or "default").strip() or "default",
    }
    with open(_METRICS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def view_counts() -> Dict[str, int]:
    if not _METRICS_PATH.is_file():
        return {}
    counts: Counter[str] = Counter()
    with open(_METRICS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                slug = (rec.get("slug") or "").strip()
                if slug:
                    counts[slug] += 1
            except Exception:
                continue
    return dict(counts)
