"""LLM bridge for deep research — AION OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx

from .research_utils import strip_thinking


def _max_report_tokens() -> int:
    try:
        return int(os.getenv("AION_DEEP_RESEARCH_MAX_TOKENS", "16384"))
    except ValueError:
        return 16384


async def complete_messages(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    timeout: float = 60.0,
) -> str:
    """Async chat completion; returns stripped text."""
    from src.runtime.llm_adapter import resolve_llm_endpoint
    from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret

    base, model = resolve_llm_endpoint()

    adapter_env = (os.getenv("AION_LLM_ADAPTER") or "").strip().lower()
    if "anthropic" in adapter_env or "anthropic" in model.lower() or "claude" in model.lower():
        provider = "anthropic"
    elif "google" in adapter_env or "gemini" in adapter_env or "gemini" in model.lower():
        provider = "google"
    else:
        provider = "openai"

    if provider == "openai":
        if not base.endswith("/v1"):
            if "/v1" in base:
                base = base.split("/v1")[0] + "/v1"
            else:
                base = base + "/v1"
        url = base + "/chat/completions"
        token = os.getenv("AION_LLM_API_KEY", "placeholder-token")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or _max_report_tokens(),
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
            msg = data["choices"][0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            return strip_thinking(content or "") or ""
        except Exception as e:
            import logging
            logging.getLogger("aion.research").warning("LLM bridge direct HTTP failed: %s", e)
            return ""
    else:
        generator = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(os.getenv("AION_LLM_API_KEY", "placeholder-token")),
            timeout=timeout,
            generation_kwargs={
                "temperature": temperature,
                "max_tokens": max_tokens or _max_report_tokens(),
            },
        )
        chat_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                chat_messages.append(ChatMessage.from_system(content))
            elif role == "assistant":
                chat_messages.append(ChatMessage.from_assistant(content))
            else:
                chat_messages.append(ChatMessage.from_user(content))

        try:
            res = await generator.run_async(messages=chat_messages)
            if res and "replies" in res and res["replies"]:
                content = res["replies"][0].text or ""
                return strip_thinking(content) or ""
        except Exception as e:
            import logging
            logging.getLogger("aion.research").warning("LLM bridge wrapper failed: %s", e)
        return ""


async def probe_model(*, timeout: float = 15.0) -> None:
    """Quick probe before a long research run."""
    await complete_messages(
        [{"role": "user", "content": "hi"}],
        temperature=0,
        max_tokens=5,
        timeout=timeout,
    )


def complete_messages_sync(
    messages: List[Dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    timeout: float = 60.0,
) -> str:
    return asyncio.get_event_loop().run_until_complete(
        complete_messages(
            messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout
        )
    )

