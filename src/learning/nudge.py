"""Nudge periodico (Hermes FASE E) — analisi retrospettiva leggera."""

from __future__ import annotations

import logging
import os
import time
from typing import Dict

from ..api.history import history_manager
from ..memory.llm_extract import complete_json_async

logger = logging.getLogger("aion.learning.nudge")

_LAST: Dict[str, float] = {}


class PeriodicNudge:
    def __init__(self) -> None:
        self.every = int(os.getenv("AION_NUDGE_EVERY", "15"))
        self.min_interval = float(os.getenv("AION_NUDGE_MIN_INTERVAL_SEC", "300"))

    async def maybe_run(
        self,
        session_id: str,
        profile_name: str,
        user_id: str,
        user_turn_count: int,
    ) -> None:
        if os.getenv("AION_NUDGE_ENABLED", "0").lower() not in ("1", "true", "yes"):
            return
        if user_turn_count <= 0 or user_turn_count % self.every != 0:
            return
        now = time.time()
        if now - _LAST.get(session_id, 0) < self.min_interval:
            return
        _LAST[session_id] = now
        rows = await history_manager.fetch_unpromoted_rows(
            session_id, profile_name, limit=self.every * 2
        )
        if not rows:
            return
        transcript = "\n".join(
            f"{r.get('role', '?')}: {(r.get('content') or '')[:600]}"
            for r in rows[-40:]
        )
        system = (
            'Rispondi JSON: {"diary_entry": "breve o null", "note": "..."} '
            "su pattern utili dalla conversazione."
        )
        try:
            await complete_json_async(system, transcript[:12000])
        except Exception as e:
            logger.debug("nudge LLM: %s", e)
        logger.info("nudge ok session=%s", session_id[:8])


periodic_nudge = PeriodicNudge()
