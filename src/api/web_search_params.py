"""Normalizzazione campi ricerca web su richiesta chat."""

from __future__ import annotations

from typing import List, Optional


def normalize_web_search_restrict_hosts(
    values: Optional[List[str]],
) -> Optional[List[str]]:
    if not values:
        return None
    seen: set[str] = set()
    out: List[str] = []
    for x in values:
        s = str(x).strip().lower()[:253]
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= 20:
            break
    return out or None
