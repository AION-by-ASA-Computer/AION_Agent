"""LLM primary + fallback routing (config-driven; stub for Haystack integration)."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("aion.llm_router")


def load_fallbacks_from_config() -> List[Dict[str, Any]]:
    try:
        import yaml
        from pathlib import Path

        p = Path("config/default.yaml")
        if not p.is_file():
            return []
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return list((cfg.get("llm") or {}).get("fallbacks") or [])
    except Exception as e:
        logger.debug("fallback config: %s", e)
        return []


def log_fallback_event(from_provider: str, to_provider: str) -> None:
    if os.getenv("AION_LLM_FALLBACK_LOG", "1").lower() not in ("1", "true", "yes"):
        return
    logger.warning("LLM fallback %s -> %s (wire Haystack generator to enable)", from_provider, to_provider)
