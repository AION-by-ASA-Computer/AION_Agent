"""Background Mnemos dream-cycle scheduler."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("aion.memory_maintenance")


def _dream_settings() -> tuple[bool, int, int]:
    enabled = os.getenv("AION_MNEMOS_DREAM_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    hour = max(0, min(23, int(os.getenv("AION_MNEMOS_DREAM_HOUR", "3"))))
    interval = max(3600, int(os.getenv("AION_MNEMOS_DREAM_INTERVAL_SEC", "86400")))
    return enabled, hour, interval


async def memory_maintenance_loop() -> None:
    """Run dream cycle on interval (default nightly)."""
    enabled, target_hour, interval = _dream_settings()
    tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"
    while True:
        if enabled:
            now = datetime.now(timezone.utc)
            if now.hour == target_hour:
                try:
                    from src.memory.mnemos.dream import run_dream_cycle

                    result = await run_dream_cycle(tenant_id=tenant)
                    logger.info("Mnemos dream cycle complete: %s", result)
                except Exception as exc:
                    logger.warning("Mnemos dream cycle error: %s", exc)
        await asyncio.sleep(interval)
