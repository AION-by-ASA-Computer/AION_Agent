"""LLM bridge for deep research — AION OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

import httpx

from .research_utils import strip_thinking


def _stream_enabled() -> bool:
    """Stream research completions (``AION_DEEP_RESEARCH_LLM_STREAM``, default on).

    Gateways in front of the LLM (the AION router behind Cloudflare/nginx)
    close a request whose response stays silent for 60 s with HTTP 504. The
    final report takes minutes to generate, so a non-streamed call always hit
    that limit and the job saved the raw "Finding N" list instead of the
    report. With streaming the tokens keep the connection alive.
    """
    return (os.getenv("AION_DEEP_RESEARCH_LLM_STREAM") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _thinking_budget() -> int:
    """Reasoning-token cap for one research call (0 = do not send the field).

    ``AION_DEEP_RESEARCH_THINKING_BUDGET`` (default 512, measured on the AION
    router: every research call shape, from the 20-token category check to the
    report, then produces visible content). The caller adds it on top of the
    call's ``max_tokens``.
    """
    try:
        configured = int(os.getenv("AION_DEEP_RESEARCH_THINKING_BUDGET", "512"))
    except ValueError:
        configured = 512
    return max(0, configured)


def _length_retry_tokens() -> int:
    """Extra max_tokens for the one retry after an empty ``finish=length`` answer.

    ``AION_DEEP_RESEARCH_LENGTH_RETRY_TOKENS`` (default 8192; 0 disables the retry).
    """
    try:
        return max(0, int(os.getenv("AION_DEEP_RESEARCH_LENGTH_RETRY_TOKENS", "8192")))
    except ValueError:
        return 8192


def _content_text(content: Any) -> str:
    """Normalise an OpenAI ``content`` value (str or list of parts) to text."""
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return content or ""


async def _post_chat(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    diag: Optional[Dict[str, Any]] = None,
    on_text: Optional[Callable[[str], None]] = None,
) -> tuple[int, str, str]:
    """POST one chat completion; return ``(status, error_text, content)``.

    Streams (SSE) when :func:`_stream_enabled`, accumulating only
    ``delta.content``: ``reasoning_content`` deltas are the model's hidden
    thinking and must never reach the report (they still keep the connection
    alive). Falls back to a plain JSON body when the server ignores ``stream``.
    On HTTP >= 400 ``content`` is empty and ``error_text`` holds the body.
    ``diag`` (optional) receives ``finish_reason`` and ``reasoning_chars`` of
    the streamed answer, logged by the caller when the content is empty.
    ``on_text`` (optional) is called with the visible content accumulated so
    far each time a streamed content delta arrives (live previews, e.g. the
    plan-execution final summary); callback errors are ignored.
    """

    def _emit(text: str) -> None:
        if on_text is None or not text:
            return
        try:
            on_text(text)
        except Exception:
            # A broken preview must never break the completion itself.
            pass

    diag = diag if diag is not None else {}
    if not _stream_enabled():
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            return r.status_code, r.text, ""
        msg = r.json()["choices"][0].get("message") or {}
        return r.status_code, "", _content_text(msg.get("content"))

    body = dict(payload)
    body["stream"] = True
    async with client.stream("POST", url, json=body, headers=headers) as r:
        if r.status_code >= 400:
            return r.status_code, (await r.aread()).decode("utf-8", "replace"), ""
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" not in ctype:
            # Server ignored stream=true and answered with one JSON body.
            data = json.loads((await r.aread()).decode("utf-8", "replace"))
            msg = data["choices"][0].get("message") or {}
            return r.status_code, "", _content_text(msg.get("content"))
        parts: List[str] = []
        async for line in r.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                event = json.loads(chunk)
            except ValueError:
                continue
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                piece = _content_text(delta.get("content"))
                parts.append(piece)
                if piece:
                    _emit("".join(parts))
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if isinstance(reasoning, str):
                    diag["reasoning_chars"] = diag.get("reasoning_chars", 0) + len(
                        reasoning
                    )
                if choice.get("finish_reason"):
                    diag["finish_reason"] = choice["finish_reason"]
        return r.status_code, "", "".join(parts)


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
    raise_errors: bool = False,
    on_text: Optional[Callable[[str], None]] = None,
) -> str:
    """Async chat completion; returns stripped text.

    Errors are logged and swallowed (``""`` returned) so one failed call does
    not abort a research round, unless ``raise_errors`` is True (used by
    :func:`probe_model` to fail fast on a broken endpoint/credential).

    ``on_text`` receives the partial visible answer while it streams (direct
    HTTP path only; the LiteLLM path is not streamed and never calls it). The
    partial text is raw: the final return value may differ after
    ``strip_thinking``.
    """
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
        # Cap hidden reasoning with vLLM's thinking_token_budget: the AION router
        # ignores chat_template_kwargs, and its Qwen model then spent the whole
        # max_tokens on reasoning_content (finish=length, empty output). The
        # budget is ADDED to max_tokens: reasoning tokens count against
        # max_tokens, so short calls (category = 20 tokens, stop check = 128)
        # were always eaten by reasoning even with a budget. Endpoints that
        # reject the field get the 400 retry below without it.
        budget = _thinking_budget()
        if budget > 0:
            payload["thinking_token_budget"] = budget
            payload["max_tokens"] = int(payload["max_tokens"]) + budget

        client_timeout = httpx.Timeout(
            timeout=float(timeout),
            connect=30.0,
            read=float(timeout),
            write=30.0,
            pool=30.0,
        )
        # ``timeout`` is a TOTAL deadline for this call, retries included. With
        # streaming, httpx's read timeout only bounds the gap between chunks,
        # so a model reasoning for 10 minutes never tripped it and one hard
        # page stalled the whole research (30-minute runs hitting the 1800 s
        # job timeout).
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(timeout)

        def _left() -> float:
            return deadline - loop.time()

        async def _bounded_post(diag: Dict[str, Any]) -> tuple[int, str, str]:
            return await asyncio.wait_for(
                _post_chat(client, url, payload, headers, diag, on_text),
                timeout=max(1.0, _left()),
            )

        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                diag: Dict[str, Any] = {}
                status, err_text, content = await _bounded_post(diag)
                # If endpoint rejected the vLLM-only fields (HTTP 400), retry without them
                if status == 400 and (
                    "chat_template_kwargs" in payload
                    or "thinking_token_budget" in payload
                ):
                    payload = dict(payload)
                    payload.pop("chat_template_kwargs", None)
                    payload.pop("thinking_token_budget", None)
                    diag = {}
                    status, err_text, content = await _bounded_post(diag)
                # Empty answer because the model reasoned until max_tokens: on long
                # prompts (page extraction, ~16k chars) the AION router's model
                # ignores thinking_token_budget and reasons ~7-8k tokens. Measured:
                # 4.6k tokens -> always empty, 12k -> content. Retry once with
                # more room instead of losing the page/analysis.
                extra = _length_retry_tokens()
                if (
                    status < 400
                    and not content
                    and diag.get("finish_reason") == "length"
                    and extra > 0
                    # Only when enough of this call's deadline is left for a
                    # longer generation; otherwise give up on this answer.
                    and _left() > float(timeout) / 2
                ):
                    payload = dict(payload)
                    payload["max_tokens"] = int(payload["max_tokens"]) + extra
                    logging.getLogger("aion.research").info(
                        "LLM bridge: empty answer at finish=length; retrying with "
                        "max_tokens=%s",
                        payload["max_tokens"],
                    )
                    diag = {}
                    status, err_text, content = await _bounded_post(diag)
                if status >= 400:
                    # Surface the endpoint's reason (e.g. the router's "Model …
                    # is not allowed for this API key") instead of a bare status:
                    # a wrong provider key/model must be visible in the job error.
                    raise httpx.HTTPStatusError(
                        f"LLM endpoint HTTP {status} for model "
                        f"'{model_name}': {err_text[:300]}",
                        request=httpx.Request("POST", url),
                        response=httpx.Response(status, text=err_text),
                    )
            # NOTE: We intentionally do NOT fall back to reasoning_content here.
            # For reasoning models (Qwen3, DeepSeek-R1, QwQ etc.) the
            # reasoning_content field contains the internal chain-of-thought, NOT
            # the final answer. Using it as a fallback causes the raw thinking
            # text to appear in the research report.
            # If content is empty the model produced no visible output — return ""
            # and let the caller apply its own fallback (e.g. use evolving_report).
            if not content:
                # finish_reason / reasoning size / prompt size tell apart "ran out
                # of tokens while reasoning" (finish=length) from a model that
                # chose to answer nothing, without logging any content.
                logging.getLogger("aion.research").warning(
                    "LLM returned empty content (finish=%s reasoning_chars=%s "
                    "max_tokens=%s prompt_chars=%s); reasoning_content suppressed "
                    "to avoid leaking thinking into report.",
                    diag.get("finish_reason"),
                    diag.get("reasoning_chars", 0),
                    payload.get("max_tokens"),
                    sum(len(str(m.get("content", ""))) for m in messages),
                )
                return ""
            return strip_thinking(content) or ""
        except asyncio.TimeoutError:
            logging.getLogger("aion.research").warning(
                "LLM bridge: no answer within %.0fs (model=%s, prompt_chars=%s); "
                "skipping this call.",
                float(timeout),
                model_name,
                sum(len(str(m.get("content", ""))) for m in messages),
            )
            if raise_errors:
                raise
            return ""
        except Exception as e:
            logging.getLogger("aion.research").warning(
                "LLM bridge direct HTTP failed: %s", e, exc_info=True
            )
            if raise_errors:
                raise
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
            # Module-level ``logging`` (a local import here would shadow it for
            # the whole function and break the HTTP branch above).
            err_str = str(e)
            logging.getLogger("aion.research").warning(
                "LLM bridge wrapper failed: %s", err_str
            )
            if raise_errors:
                raise
            # Swallow the "model output must contain either output text or tool
            # calls" error that LiteLLM/Haystack raises when a reasoning model
            # returns an empty visible-content response (all tokens in think
            # block). Returning "" lets the caller apply its own fallback.
            return ""
        return ""


async def probe_model(*, timeout: float = 15.0) -> None:
    """Quick probe before a long research run.

    Raises when the LLM endpoint is unreachable or rejects the request (bad
    key, unknown model…), so ``ResearchHandler`` marks the job as ``error``
    with the reason instead of running every phase on empty LLM output and
    saving an empty "completed" report. An empty answer is not an error here:
    reasoning models may spend the 5 probe tokens on hidden thinking.
    """
    await complete_messages(
        [{"role": "user", "content": "hi"}],
        temperature=0,
        max_tokens=5,
        timeout=timeout,
        raise_errors=True,
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
