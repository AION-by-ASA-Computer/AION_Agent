"""JSON completion helper for LTM extraction (OpenAI-compatible vLLM endpoint)."""

import json
import logging
import os
import re
import asyncio
from typing import Any, Dict, List, Optional

from haystack.dataclasses import ChatMessage

from src.haystack_chat import chat_message_text

logger = logging.getLogger("aion.memory.llm_extract")


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if m:
        return m.group(1).strip()
    return text


def _fallback_ltm_should_persist(text: str) -> Optional[Dict[str, Any]]:
    """Se il modello tronca il JSON, prova almeno a leggere should_persist."""
    m = re.search(r'"should_persist"\s*:\s*(true|false)', text, re.I)
    if not m:
        m = re.search(r"'should_persist'\s*:\s*(true|false)", text, re.I)
    if not m:
        return None
    sp = m.group(1).lower() == "true"
    return {"should_persist": sp, "reason": "truncated_json_heuristic"}


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from model output: full string, fenced block, or first {...} span."""
    if not text or not str(text).strip():
        return None
    raw = _strip_json_fence(str(text).strip())
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        pass
    # Primo oggetto JSON bilanciato (modelli che aggiungono testo prima/dopo)
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i, ch in enumerate(raw[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    out = json.loads(raw[start : i + 1])
                    return out if isinstance(out, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def complete_json_sync(
    system_prompt: str, user_prompt: str, timeout: Optional[float] = None
) -> Dict[str, Any]:
    """Blocking chat completion using LiteLLM wrapper; returns parsed JSON object (minimum: should_persist)."""
    if timeout is None:
        timeout = float(os.getenv("AION_LTM_EXTRACT_HTTP_TIMEOUT", "45"))
    from src.runtime.llm_adapter import resolve_llm_credentials
    from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret

    base, model, token = resolve_llm_credentials()

    max_tokens = int(os.getenv("AION_LTM_EXTRACT_MAX_TOKENS", "1024"))
    gen_kwargs = {
        "temperature": 0.4,
        "max_tokens": max_tokens,
    }
    if os.getenv("AION_LTM_JSON_RESPONSE_FORMAT", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        gen_kwargs["response_format"] = {"type": "json_object"}

    generator = LiteLLMChatGeneratorWrapper(
        model=model,
        api_base_url=base,
        api_key=Secret.from_token(token),
        timeout=timeout,
        generation_kwargs=gen_kwargs,
    )
    messages = [
        ChatMessage.from_system(system_prompt),
        ChatMessage.from_user(user_prompt),
    ]
    try:
        res = generator.run(messages=messages)
        if not res or "replies" not in res or not res["replies"]:
            logger.debug("LTM extract: empty replies from wrapper")
            return {"should_persist": False, "reason": "empty_content"}
        content = res["replies"][0].text
    except Exception as e:
        logger.warning("LTM extraction LLM failed: %s", e)
        return {"should_persist": False, "reason": "api_call_failed"}

    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    if content is None or (isinstance(content, str) and not content.strip()):
        logger.debug("LTM extract: empty message content from model.")
        return {"should_persist": False, "reason": "empty_content"}
    parsed = _extract_json_object(str(content))
    if parsed is None:
        # Retry with simpler prompt if empty/bad but we want to try again
        if (
            not content or not content.strip()
        ) and "SIMPLIFIED_RETRY" not in system_prompt:
            logger.debug(
                "LTM extract: Empty response, retrying with simplified prompt..."
            )
            simple_system = 'Rispondi solo con JSON: {"should_persist": false, "reason": "no_info"} se non c\'è nulla di rilevante, altrimenti estrai i fatti in JSON LTM.'
            return complete_json_sync(
                simple_system, user_prompt + "\n\nSIMPLIFIED_RETRY", timeout
            )

        fb = _fallback_ltm_should_persist(str(content))
        if fb is not None:
            logger.debug(
                "LTM extract: JSON incompleto, uso fallback should_persist=%s",
                fb.get("should_persist"),
            )
            return fb
        logger.debug(
            "LTM extract: could not parse JSON from: %s...", str(content)[:200]
        )
        return {"should_persist": False, "reason": "parse_failed"}
    return parsed


def _env_disable_flag(name: str, *, default: bool = True) -> bool:
    """True when the named *DISABLE* env var is on (default if unset)."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _text_completion_generation_kwargs(
    max_tokens: int,
    *,
    disable_reasoning: Optional[bool] = None,
) -> Dict[str, Any]:
    """Generation kwargs for short factual completions (benchmark judge, summaries)."""
    kwargs: Dict[str, Any] = {
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if disable_reasoning is None:
        disable_reasoning = _env_disable_flag(
            "AION_TEXT_COMPLETION_DISABLE_REASONING", default=True
        )
    if disable_reasoning:
        from src.runtime.reasoning_effort import merge_generation_kwargs

        return merge_generation_kwargs(kwargs, "min")
    return kwargs


def extract_reply_text(message: ChatMessage) -> str:
    """Best-effort assistant text (incl. reasoning-only models)."""
    text = (chat_message_text(message) or "").strip()
    if text:
        return text
    meta = getattr(message, "meta", None) or {}
    for key in ("reasoning_content", "reasoning"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


async def complete_json_async(
    system_prompt: str, user_prompt: str, timeout: Optional[float] = None
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        complete_json_sync, system_prompt, user_prompt, timeout
    )


def complete_text_sync(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 800,
    timeout: float = 60.0,
    disable_reasoning: Optional[bool] = None,
) -> str:
    return complete_text_sync_detailed(
        system_prompt,
        user_prompt,
        max_tokens=max_tokens,
        timeout=timeout,
        disable_reasoning=disable_reasoning,
    ).get("text", "")


def complete_text_sync_detailed(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 800,
    timeout: float = 60.0,
    disable_reasoning: Optional[bool] = None,
) -> Dict[str, Any]:
    """Chat completion with diagnostic payload for benchmark tracing."""
    from src.runtime.llm_adapter import resolve_llm_credentials
    from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret

    base, model, token = resolve_llm_credentials()
    gen_kwargs = _text_completion_generation_kwargs(
        max_tokens, disable_reasoning=disable_reasoning
    )
    out: Dict[str, Any] = {
        "text": "",
        "api_base_url": base,
        "model": model,
        "generation_kwargs": gen_kwargs,
        "finish_reason": None,
        "usage": None,
        "meta": {},
        "raw_text": "",
        "chat_message_text": "",
        "reasoning_preview": "",
        "retried": False,
        "error": None,
    }

    messages = [
        ChatMessage.from_system(system_prompt),
        ChatMessage.from_user(user_prompt),
    ]

    def _read_reply(res: Dict[str, Any]) -> str:
        if not res or "replies" not in res or not res["replies"]:
            return ""
        msg = res["replies"][0]
        out["meta"] = dict(getattr(msg, "meta", None) or {})
        out["finish_reason"] = out["meta"].get("finish_reason")
        out["usage"] = out["meta"].get("usage")
        out["chat_message_text"] = chat_message_text(msg)
        for key in ("reasoning_content", "reasoning"):
            val = out["meta"].get(key)
            if isinstance(val, str) and val.strip():
                out["reasoning_preview"] = val.strip()[:2000]
                break
        raw = extract_reply_text(msg)
        out["raw_text"] = raw
        return raw

    try:
        generator = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(token),
            timeout=timeout,
            generation_kwargs=gen_kwargs,
        )
        res = generator.run(messages=messages)
        text = _read_reply(res)
        if text:
            out["text"] = text
            return out

        if disable_reasoning is not False:
            logger.warning(
                "Text completion returned empty content (model=%s finish=%s)",
                model,
                out.get("finish_reason"),
            )
            return out

        out["retried"] = True
        retry_kwargs = _text_completion_generation_kwargs(
            max_tokens, disable_reasoning=True
        )
        retry_gen = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(token),
            timeout=timeout,
            generation_kwargs=retry_kwargs,
        )
        retry_res = retry_gen.run(messages=messages)
        text = _read_reply(retry_res)
        out["generation_kwargs"] = retry_kwargs
        if text:
            out["text"] = text
            return out

        logger.warning(
            "Text completion returned empty content (model=%s finish=%s)",
            model,
            out.get("finish_reason"),
        )
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        logger.warning("Text completion LLM failed: %s", e)
    return out


async def complete_text_async(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 800,
    timeout: float = 60.0,
    disable_reasoning: Optional[bool] = None,
) -> str:
    detail = await complete_text_async_detailed(
        system_prompt,
        user_prompt,
        max_tokens=max_tokens,
        timeout=timeout,
        disable_reasoning=disable_reasoning,
    )
    return detail.get("text", "")


async def complete_text_async_detailed(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 800,
    timeout: float = 60.0,
    disable_reasoning: Optional[bool] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        complete_text_sync_detailed,
        system_prompt,
        user_prompt,
        max_tokens=max_tokens,
        timeout=timeout,
        disable_reasoning=disable_reasoning,
    )
