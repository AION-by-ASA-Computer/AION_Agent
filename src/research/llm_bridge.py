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
    from src.runtime.llm_adapter import resolve_llm_credentials
    from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret

    base, model, token = resolve_llm_credentials()

    adapter_env = (os.getenv("AION_LLM_ADAPTER") or "").strip().lower()
    if (
        "anthropic" in adapter_env
        or "anthropic" in model.lower()
        or "claude" in model.lower()
    ):
        provider = "anthropic"
    elif (
        "google" in adapter_env or "gemini" in adapter_env or "gemini" in model.lower()
    ):
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
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        model_name = model
        if "/" in model_name:
            parts = model_name.split("/", 1)
            if parts[0] in (
                "vllm",
                "openai",
                "ollama",
                "openrouter",
                "deepinfra",
                "groq",
                "together",
                "anyscale",
                "perplexity",
                "mistral",
                "fireworks",
            ):
                model_name = parts[1]

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or _max_report_tokens(),
        }
        # For reasoning models (Qwen 3, QwQ, DeepSeek) served via vLLM/Ollama,
        # request that internal thinking is disabled so the model generates the report
        # directly in 'content' without exhausting all completion tokens on hidden reasoning monologue.
        is_reasoning_model = any(
            x in (model_name or "").lower() or x in (base or "").lower()
            for x in ("qwen", "qwq", "deepseek", "r1")
        )
        if is_reasoning_model:
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        client_timeout = httpx.Timeout(
            timeout=float(timeout),
            connect=30.0,
            read=float(timeout),
            write=30.0,
            pool=30.0,
        )
        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
                # If endpoint rejected chat_template_kwargs (HTTP 400), retry without it
                if r.status_code == 400 and "chat_template_kwargs" in payload:
                    retry_payload = dict(payload)
                    retry_payload.pop("chat_template_kwargs", None)
                    r = await client.post(url, json=retry_payload, headers=headers)
                r.raise_for_status()
                data = r.json()
            msg = data["choices"][0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            # NOTE: We intentionally do NOT fall back to reasoning_content here.
            # For reasoning models (Qwen3, DeepSeek-R1, QwQ etc.) the
            # reasoning_content field contains the internal chain-of-thought, NOT
            # the final answer. Using it as a fallback causes the raw thinking
            # text to appear in the research report.
            # If content is empty the model produced no visible output — return ""
            # and let the caller apply its own fallback (e.g. use evolving_report).
            if not content:
                import logging as _log

                _log.getLogger("aion.research").warning(
                    "LLM returned empty content (reasoning model with no visible output?); "
                    "reasoning_content suppressed to avoid leaking thinking into report."
                )
                return ""
            return strip_thinking(content) or ""
        except Exception as e:
            import logging

            logging.getLogger("aion.research").warning(
                "LLM bridge direct HTTP failed: %s", e, exc_info=True
            )
            return ""
    else:
        gen_kwargs: Dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens or _max_report_tokens(),
        }
        if any(
            x in (model or "").lower() or x in (base or "").lower()
            for x in ("qwen", "qwq", "deepseek", "r1")
        ):
            gen_kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }

        generator = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(token),
            timeout=timeout,
            generation_kwargs=gen_kwargs,
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
                reply = res["replies"][0]
                content = reply.text or ""
                # NOTE: We intentionally do NOT fall back to reasoning_content here.
                # For reasoning models (Qwen3, DeepSeek-R1, QwQ, Claude Extended Thinking
                # etc.) the reasoning_content / reasoning field contains the internal
                # chain-of-thought, NOT the final answer. Using it as a fallback causes
                # the raw thinking text to appear in the research report.
                # If content is empty the model produced no visible output — return ""
                # and let the caller apply its own fallback (e.g. use evolving_report).
                if not content:
                    import logging as _log

                    _log.getLogger("aion.research").warning(
                        "LLM wrapper returned empty text (reasoning model with no visible output?); "
                        "reasoning_content suppressed to avoid leaking thinking into report."
                    )
                    return ""
                return strip_thinking(content) or ""
        except Exception as e:
            import logging

            err_str = str(e)
            logging.getLogger("aion.research").warning(
                "LLM bridge wrapper failed: %s", err_str
            )
            # Swallow the "model output must contain either output text or tool
            # calls" error that LiteLLM/Haystack raises when a reasoning model
            # returns an empty visible-content response (all tokens in think
            # block). Returning "" lets the caller apply its own fallback.
            return ""
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
