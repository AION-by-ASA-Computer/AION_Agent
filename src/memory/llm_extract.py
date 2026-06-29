"""JSON completion helper for LTM extraction (OpenAI-compatible vLLM endpoint)."""

import json
import logging
import os
import re
import asyncio
from typing import Any, Dict, List, Optional

import requests

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
    """Blocking OpenAI-compatible chat completion; returns parsed JSON object (minimo: should_persist)."""
    if timeout is None:
        timeout = float(os.getenv("AION_LTM_EXTRACT_HTTP_TIMEOUT", "45"))
    from src.runtime.llm_adapter import resolve_llm_endpoint
    from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret

    base, model = resolve_llm_endpoint()

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
        max_tokens = int(os.getenv("AION_LTM_EXTRACT_MAX_TOKENS", "1024"))
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        if os.getenv("AION_LTM_JSON_RESPONSE_FORMAT", "0").lower() in (
            "1",
            "true",
            "yes",
        ):
            payload["response_format"] = {"type": "json_object"}
        token = os.getenv("AION_LLM_API_KEY", "placeholder-token")
        try:
            r = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            msg = choice.get("message") or {}
            content = msg.get("content")
        except Exception as e:
            logger.warning("LTM extraction direct HTTP failed: %s", e)
            return {"should_persist": False, "reason": "api_call_failed"}
    else:
        max_tokens = int(os.getenv("AION_LTM_EXTRACT_MAX_TOKENS", "1024"))
        gen_kwargs = {
            "temperature": 0.4,
            "max_tokens": max_tokens,
        }
        generator = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(
                os.getenv("AION_LLM_API_KEY", "placeholder-token")
            ),
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
) -> str:
    """Chat completion testuale (session search summary, ecc.)."""
    from src.runtime.llm_adapter import resolve_llm_endpoint
    from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
    from haystack.dataclasses import ChatMessage
    from haystack.utils import Secret

    base, model = resolve_llm_endpoint()

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
        token = os.getenv("AION_LLM_API_KEY", "placeholder-token")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        try:
            r = requests.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            msg = data["choices"][0].get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            return (content or "").strip()
        except Exception as e:
            logger.warning("Text completion direct HTTP failed: %s", e)
            return ""
    else:
        generator = LiteLLMChatGeneratorWrapper(
            model=model,
            api_base_url=base,
            api_key=Secret.from_token(
                os.getenv("AION_LLM_API_KEY", "placeholder-token")
            ),
            timeout=timeout,
            generation_kwargs={
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
        )
        messages = [
            ChatMessage.from_system(system_prompt),
            ChatMessage.from_user(user_prompt),
        ]
        try:
            res = generator.run(messages=messages)
            if res and "replies" in res and res["replies"]:
                return (res["replies"][0].text or "").strip()
        except Exception as e:
            logger.warning("Text completion LLM failed: %s", e)
        return ""
