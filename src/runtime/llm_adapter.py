"""Resolve LLM endpoint and model from environment (no hardcoded private IPs)."""
from __future__ import annotations

import logging
import os
from typing import Tuple

logger = logging.getLogger("aion.llm_generator")


def resolve_llm_endpoint() -> Tuple[str, str]:
    """
    Returns (api_url, model_name). Raises ValueError if either is missing.
    """
    url = (os.getenv("AION_API_URL") or "").strip().rstrip("/")
    model = (os.getenv("AION_MODEL") or "").strip()
    if not url:
        raise ValueError(
            "AION_API_URL is required. Set it to your OpenAI-compatible LLM endpoint."
        )
    if not model:
        raise ValueError("AION_MODEL is required. Set it to your model identifier.")
    return url, model


def resolve_llm_adapter() -> str:
    return (os.getenv("AION_LLM_ADAPTER") or "vllm_qwen").strip()


def resolve_llm_timeout(default: int = 120) -> int:
    try:
        return int(os.getenv("AION_LLM_TIMEOUT", str(default)))
    except ValueError:
        return default
