"""Patch skill generate (Hermes FASE C) — stub sicuro."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.learning.patcher")


class SkillPatcher:
    async def propose_patch(
        self,
        name: str,
        new_data: Dict[str, Any],
        reason: str = "",
    ) -> Optional[str]:
        if os.getenv("AION_SKILL_PATCH_ENABLED", "0").lower() not in (
            "1",
            "true",
            "yes",
        ):
            return None
        logger.info("skill_patch stub: %s (%s)", name, reason)
        return None


skill_patcher = SkillPatcher()
