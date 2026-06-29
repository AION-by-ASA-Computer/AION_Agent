"""Compattazione output sub-agent per payload del task successivo (senza accoppiamento al compressor STM)."""
from __future__ import annotations

import os
import re


_WS = re.compile(r"\s+")


def distill_subagent_output(text: str, *, max_chars: int | None = None) -> str:
    """
    Riduce la dimensione del testo restituito da un sub-agente.
    Default: ``AION_ORCH_DISTILL_MAX_CHARS`` (8000). Oltre soglia: testa+coda con omissis centrale.
    """
    limit = max_chars if max_chars is not None else int(os.getenv("AION_ORCH_DISTILL_MAX_CHARS", "8000"))
    t = _WS.sub(" ", (text or "").strip())
    if len(t) <= limit:
        return t
    head = max(512, limit // 2)
    tail = max(256, limit - head - 24)
    return t[:head] + "\n… [omissis] …\n" + t[-tail:]
