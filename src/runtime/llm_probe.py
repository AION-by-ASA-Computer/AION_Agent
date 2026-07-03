"""Probe LLM endpoints: connectivity check and model discovery (SmartRoute-style)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from src.runtime.llm_adapter import normalize_litellm_provider

logger = logging.getLogger("aion.llm_probe")

_OFFICIAL_VENDOR_HOSTS = frozenset(
    {
        "api.openai.com",
        "api.anthropic.com",
        "api.groq.com",
        "api.together.xyz",
        "api.fireworks.ai",
        "api.mistral.ai",
        "api.deepseek.com",
        "openrouter.ai",
        "generativelanguage.googleapis.com",
        "aiplatform.googleapis.com",
    }
)

_URL_PROVIDER_HINTS: list[tuple[str, str]] = [
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
    ("api.groq.com", "groq"),
    ("api.together.xyz", "together_ai"),
    ("api.fireworks.ai", "fireworks_ai"),
    ("api.mistral.ai", "mistral"),
    ("api.deepseek.com", "deepseek"),
    ("openrouter.ai", "openrouter"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("aiplatform.googleapis.com", "vertex_ai"),
    ("localhost:11434", "ollama"),
    ("127.0.0.1:11434", "ollama"),
    ("localhost:1234", "openai"),
    ("localhost:8000", "openai"),
]

_PROVIDER_DEFAULT_BASE_URL: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "google": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://localhost:11434/v1",
}


def _normalize_url(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if u and not u.startswith(("http://", "https://")):
        u = "http://" + u
    return u


def resolve_probe_base_url(provider: str, api_base_url: Optional[str]) -> str:
    """Resolve the base URL used for GET /models during probe."""
    explicit = _normalize_url(api_base_url or "")
    if explicit:
        return explicit
    return _PROVIDER_DEFAULT_BASE_URL.get((provider or "openai").strip().lower(), "")


def infer_litellm_provider(provider: str, base_url: str) -> str:
    """Map AION provider id + URL to LiteLLM routing provider."""
    p = (provider or "openai").strip().lower()
    if p == "gemini":
        p = "gemini"
    litellm_p = normalize_litellm_provider(p, base_url)
    if litellm_p != p:
        return litellm_p
    host = urlparse(base_url).netloc.lower()
    for hint, hinted in _URL_PROVIDER_HINTS:
        if hint in host or host in hint:
            return hinted
    return litellm_p


def is_official_vendor_endpoint(base_url: str) -> bool:
    host = urlparse(base_url).netloc.lower().split(":")[0]
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return False
    if host in _OFFICIAL_VENDOR_HOSTS:
        return True
    return any(official in host for official in _OFFICIAL_VENDOR_HOSTS)


def should_use_catalog_fallback(provider: str, base_url: str) -> bool:
    """Static LiteLLM catalog only for official cloud APIs, not self-hosted."""
    if (provider or "").strip().lower() in ("ollama", "vllm"):
        return False
    return is_official_vendor_endpoint(base_url)


def list_catalog_models(litellm_provider: str) -> List[str]:
    try:
        from litellm import get_valid_models

        models = get_valid_models(custom_llm_provider=litellm_provider)
        return sorted(set(models)) if models else []
    except Exception as e:
        logger.warning("LiteLLM catalog for %s failed: %s", litellm_provider, e)
        return []


def catalog_to_openai_models(models: List[str]) -> Dict[str, Any]:
    return {"data": [{"id": m} for m in models], "object": "list"}


def model_context_hint(litellm_provider: str, model_id: str) -> Dict[str, int]:
    """Best-effort context window + safe max output tokens from LiteLLM catalog."""
    litellm_model = model_id if "/" in model_id else f"{litellm_provider}/{model_id}"
    context_window = 32768
    try:
        import litellm

        info = litellm.get_model_info(litellm_model)
        if info:
            context_window = int(
                info.get("max_tokens")
                or info.get("max_input_tokens")
                or info.get("max_output_tokens")
                or 32768
            )
    except Exception:
        pass
    # Reserve headroom for prompt + thinking budget; cap suggested output tokens.
    suggested_max_chat_tokens = min(8192, max(1024, context_window // 8))
    return {
        "context_window": context_window,
        "suggested_max_chat_tokens": suggested_max_chat_tokens,
    }


def enrich_models_payload(
    models_payload: Dict[str, Any], litellm_provider: str
) -> Dict[str, Any]:
    """Attach per-model context hints for setup validation."""
    data = models_payload.get("data") or []
    hints: Dict[str, Dict[str, int]] = {}
    for item in data:
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        hints[mid] = model_context_hint(litellm_provider, mid)
    return {**models_payload, "hints": hints}


async def _fetch_live_model_ids(
    base_url: str, api_key: Optional[str], timeout: float = 10.0
) -> List[str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key and key.lower() not in ("none", "placeholder-token"):
        headers["Authorization"] = f"Bearer {key}"
    endpoint = base_url.rstrip("/") + "/models"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(endpoint, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return [
        str(m.get("id", "")).strip()
        for m in (data.get("data") or [])
        if m.get("id")
    ]


async def probe_llm_connection(
    *,
    provider: str,
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Test connectivity and list models (live GET /v1/models, LiteLLM catalog fallback).

    Raises ValueError for missing required configuration.
    """
    p = (provider or "openai").strip().lower()
    base_url = resolve_probe_base_url(p, api_base_url)
    if not base_url:
        raise ValueError(
            "API base URL is required for this provider (e.g. vLLM endpoint)."
        )

    litellm_provider = infer_litellm_provider(p, base_url)
    use_catalog = should_use_catalog_fallback(p, base_url)
    catalog = list_catalog_models(litellm_provider) if use_catalog else []

    start = time.monotonic()
    warning: Optional[str] = None
    models_source = "live"
    live_ids: List[str] = []

    try:
        live_ids = await _fetch_live_model_ids(base_url, api_key)
    except Exception as e:
        logger.info("Live /models probe failed for %s: %s", base_url, e)
        if not catalog:
            raise ValueError(
                f"Endpoint unreachable ({base_url}). "
                "Check URL, API key, and that GET /v1/models returns available models. "
                f"Detail: {e}"
            ) from e
        warning = f"Live probe failed, showing LiteLLM catalog only: {e}"
        models_source = "catalog"

    if live_ids:
        models_payload = catalog_to_openai_models(live_ids)
        if use_catalog and catalog and len(live_ids) > len(catalog):
            models_source = "live"
    elif catalog:
        models_payload = catalog_to_openai_models(catalog)
        models_source = "catalog"
    else:
        models_payload = catalog_to_openai_models([])
        models_source = "live"
        warning = (
            warning
            or "Endpoint reachable but returned no models. Enter the model name manually."
        )

    latency_ms = (time.monotonic() - start) * 1000
    enriched = enrich_models_payload(models_payload, litellm_provider)

    return {
        "healthy": True,
        "latency_ms": round(latency_ms, 1),
        "litellm_provider": litellm_provider,
        "base_url": base_url,
        "catalog_count": len(catalog),
        "models_source": models_source,
        "models": enriched,
        "warning": warning,
    }
