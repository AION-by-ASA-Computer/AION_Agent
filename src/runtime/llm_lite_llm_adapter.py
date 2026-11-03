"""Adapter LiteLLM per LLM providers multipli."""

from __future__ import annotations

import inspect
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from haystack import component
from haystack.dataclasses import ChatMessage, StreamingChunk
from haystack.utils.auth import Secret

from src.runtime.llm_adapter import normalize_litellm_provider

logger = logging.getLogger("aion.lite_llm")


# --- Monkeypatch per supportare l'estrazione di reasoning_content da LiteLLM ---
try:
    import haystack_integrations.components.generators.litellm.chat.chat_generator as litellm_chat_mod

    _original_convert = litellm_chat_mod._convert_litellm_chunk_to_streaming_chunk

    def _patched_convert_litellm_chunk_to_streaming_chunk(
        chunk, previous_chunks, component_info
    ):
        stream_chunk = _original_convert(chunk, previous_chunks, component_info)

        # Estrai reasoning_content da LiteLLM (es. DeepSeek, Gemini, Claude 3.7, OpenAI o3-mini)
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if not reasoning and isinstance(delta, dict):
                reasoning = delta.get("reasoning_content")
            if not reasoning:
                reasoning = getattr(delta, "reasoning", None)
                if not reasoning and isinstance(delta, dict):
                    reasoning = delta.get("reasoning")

            if reasoning:
                if stream_chunk.meta is None:
                    stream_chunk.meta = {}
                stream_chunk.meta["reasoning"] = reasoning
                stream_chunk.meta["reasoning_content"] = reasoning

        # AION Custom Events Support
        aion_event_type = getattr(chunk, "aion_event_type", None)
        if not aion_event_type and hasattr(chunk, "model_extra") and chunk.model_extra:
            aion_event_type = chunk.model_extra.get("aion_event_type")
        if aion_event_type:
            if stream_chunk.meta is None:
                stream_chunk.meta = {}
            stream_chunk.meta["aion_event_type"] = aion_event_type
            stream_chunk.meta["data"] = getattr(chunk, "data", None)
            if (
                not stream_chunk.meta["data"]
                and hasattr(chunk, "model_extra")
                and chunk.model_extra
            ):
                stream_chunk.meta["data"] = chunk.model_extra.get("data")

        return stream_chunk

    litellm_chat_mod._convert_litellm_chunk_to_streaming_chunk = (
        _patched_convert_litellm_chunk_to_streaming_chunk
    )
    logger.info(
        "Successfully applied monkeypatch to _convert_litellm_chunk_to_streaming_chunk for reasoning extraction."
    )
except Exception as e:
    logger.warning(
        "Failed to apply monkeypatch for LiteLLM reasoning extraction: %s", e
    )


# --- Reasoning replay (interleaved thinking) -------------------------------
# Il reasoning prodotto dal modello a ogni step del loop tool viene salvato come
# ReasoningContent sul ChatMessage assistente e rimandato al server allo step
# successivo (campi `reasoning_content` / `reasoning`, come i local carriers di
# Hermes). I messaggi ricostruiti da STM/cronologia sono solo testo, quindi il
# replay resta confinato al turno corrente.

_REPLAY_SKIP_PROVIDERS = ("anthropic", "google", "gemini", "vertex_ai", "bedrock")


def reasoning_replay_enabled() -> bool:
    import os

    raw = os.environ.get("AION_REASONING_REPLAY", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def reasoning_replay_fields() -> List[str]:
    import os

    raw = os.environ.get("AION_REASONING_REPLAY_FIELDS", "reasoning_content,reasoning")
    return [f.strip() for f in raw.split(",") if f.strip()]


def _reasoning_from_message_obj(message: Any) -> str:
    for key in ("reasoning_content", "reasoning"):
        val = getattr(message, key, None)
        if not val and isinstance(message, dict):
            val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _with_reasoning(msg: ChatMessage, reasoning_text: str) -> ChatMessage:
    if not reasoning_text or getattr(msg, "reasoning", None) is not None:
        return msg
    # Un assistente con solo reasoning non è serializzabile in formato OpenAI
    # (to_openai_dict_format richiede testo o tool call): lo lasciamo com'era.
    if not msg.text and not msg.tool_calls:
        return msg
    from haystack.dataclasses import ReasoningContent

    return ChatMessage.from_assistant(
        text=msg.text,
        tool_calls=msg.tool_calls,
        meta=msg.meta,
        name=msg.name,
        reasoning=ReasoningContent(reasoning_text=reasoning_text),
    )


try:
    import haystack_integrations.components.generators.litellm.chat.chat_generator as litellm_chat_mod
    from haystack_integrations.components.generators.litellm import (
        LiteLLMChatGenerator as _LiteLLMChatGenerator,
    )

    _original_build_chat_message = litellm_chat_mod._build_chat_message
    _original_streaming_to_message = (
        litellm_chat_mod._convert_streaming_chunks_to_chat_message
    )
    _original_build_litellm_kwargs = _LiteLLMChatGenerator._build_litellm_kwargs

    def _patched_build_chat_message(response, choice):
        msg = _original_build_chat_message(response, choice)
        return _with_reasoning(
            msg, _reasoning_from_message_obj(getattr(choice, "message", None))
        )

    def _patched_streaming_to_message(chunks):
        msg = _original_streaming_to_message(chunks=chunks)
        # La patch sui chunk mette il reasoning solo in meta (non in chunk.reasoning,
        # per non duplicare l'emissione verso la UI): lo riaggreghiamo qui.
        parts = [
            str((c.meta or {}).get("reasoning") or "")
            for c in chunks
            if c.reasoning is None
        ]
        return _with_reasoning(msg, "".join(parts))

    def _patched_build_litellm_kwargs(
        self, messages, streaming_callback, generation_kwargs, tools
    ):
        kwargs = _original_build_litellm_kwargs(
            self, messages, streaming_callback, generation_kwargs, tools
        )
        provider = str(getattr(self, "model", "") or "").split("/", 1)[0].lower()
        if not reasoning_replay_enabled() or provider in _REPLAY_SKIP_PROVIDERS:
            return kwargs
        fields = reasoning_replay_fields()
        wire = kwargs.get("messages") or []
        if not fields or len(wire) != len(messages):
            return kwargs
        for hm, om in zip(messages, wire):
            rc = getattr(hm, "reasoning", None)
            text = getattr(rc, "reasoning_text", None) if rc is not None else None
            if not text or not isinstance(om, dict) or om.get("role") != "assistant":
                continue
            for field in fields:
                om.setdefault(field, text)
        return kwargs

    litellm_chat_mod._build_chat_message = _patched_build_chat_message
    litellm_chat_mod._convert_streaming_chunks_to_chat_message = (
        _patched_streaming_to_message
    )
    _LiteLLMChatGenerator._build_litellm_kwargs = _patched_build_litellm_kwargs
except Exception as e:
    logger.warning("Failed to apply monkeypatch for LiteLLM reasoning replay: %s", e)


def _sanitize_messages_for_litellm(messages: List[ChatMessage]) -> List[ChatMessage]:
    """Ensure all ChatMessage instances contain at least one content item so to_openai_dict_format doesn't crash."""
    if not messages:
        return messages
    from haystack.dataclasses import ChatRole, TextContent

    sanitized = []
    for m in messages:
        content = getattr(m, "_content", None)
        if not content:
            text_val = getattr(m, "text", "") or " "
            role = getattr(m, "_role", ChatRole.ASSISTANT)
            sanitized.append(
                ChatMessage(
                    role=role,
                    content=[TextContent(text=text_val)],
                    meta=getattr(m, "meta", {}),
                )
            )
        else:
            sanitized.append(m)
    return sanitized


@component
class LiteLLMChatGeneratorWrapper:
    """
    Wrapper per LiteLLMChatGenerator che supporta 100+ provider LLM.
    Formato modello: provider/model-name (es. openai/gpt-4o, anthropic/claude-sonnet-4-20250514)
    """

    def __init__(
        self,
        model: str,
        api_base_url: Optional[str] = None,
        api_key: Optional[Secret] = None,
        timeout: Optional[float] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
        tools_strict: Optional[bool] = None,
        **kwargs,
    ):
        self.model = model
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.timeout = timeout
        self._initial_generation_kwargs = generation_kwargs
        self.tools_strict = tools_strict
        self.extra_kwargs = kwargs

        # Estrai provider e model-name dal formato "provider/model-name"
        if "/" in model:
            self.provider, self.model_name = model.split("/", 1)
        else:
            self.provider = "openai"
            self.model_name = model

        self.provider = normalize_litellm_provider(self.provider, api_base_url)

        # Inizializza generatore LiteLLM
        self.generator = self._instantiate_generator()

    def _instantiate_generator(self) -> Any:
        from haystack_integrations.components.generators.litellm import (
            LiteLLMChatGenerator,
        )

        gen_cls = LiteLLMChatGenerator

        init_params = {
            "model": f"{self.provider}/{self.model_name}",
            "api_key": self.api_key,
            "generation_kwargs": self._initial_generation_kwargs,
        }

        if self.api_base_url is not None:
            init_params["api_base_url"] = self.api_base_url
        if self.timeout is not None:
            init_params["timeout"] = self.timeout
        if self.tools_strict is not None:
            init_params["tools_strict"] = self.tools_strict

        init_params.update(self.extra_kwargs)

        # Filtra parametri in base alla firma del generatore
        sig = inspect.signature(gen_cls.__init__)
        has_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if has_kwargs:
            filtered_params = init_params
        else:
            filtered_params = {
                k: v for k, v in init_params.items() if k in sig.parameters
            }

        return gen_cls(**filtered_params)

    @property
    def generation_kwargs(self) -> Dict[str, Any]:
        return getattr(self.generator, "generation_kwargs", {})

    @generation_kwargs.setter
    def generation_kwargs(self, value: Dict[str, Any]):
        if hasattr(self.generator, "generation_kwargs"):
            self.generator.generation_kwargs = value

    def warm_up(self) -> None:
        if hasattr(self.generator, "warm_up"):
            self.generator.warm_up()

    @component.output_types(replies=List[ChatMessage])
    def run(
        self,
        messages: List[ChatMessage],
        streaming_callback: Optional[Callable[[StreamingChunk], None]] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        **kwargs,
    ) -> Dict[str, List[ChatMessage]]:
        messages = _sanitize_messages_for_litellm(messages)
        run_params = {
            "messages": messages,
            "streaming_callback": streaming_callback,
            "generation_kwargs": generation_kwargs,
            "tools": tools,
        }
        run_params.update(kwargs)

        run_sig = inspect.signature(self.generator.run)
        has_run_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in run_sig.parameters.values()
        )
        if has_run_kwargs:
            filtered_run_params = run_params
        else:
            filtered_run_params = {
                k: v for k, v in run_params.items() if k in run_sig.parameters
            }

        from src.runtime.llm_call_audit import llm_call_audit_enabled, record_llm_call

        t0 = time.time() if llm_call_audit_enabled() else 0.0
        try:
            result = self.generator.run(**filtered_run_params)
        except Exception as exc:
            if llm_call_audit_enabled():
                record_llm_call(
                    self,
                    messages=messages,
                    tools=tools,
                    generation_kwargs=generation_kwargs,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((time.time() - t0) * 1000),
                )
            raise
        if llm_call_audit_enabled():
            record_llm_call(
                self,
                messages=messages,
                tools=tools,
                generation_kwargs=generation_kwargs,
                result=result,
                duration_ms=int((time.time() - t0) * 1000),
            )
        return result

    @component.output_types(replies=List[ChatMessage])
    async def run_async(
        self,
        messages: List[ChatMessage],
        streaming_callback: Optional[Callable[[StreamingChunk], None]] = None,
        generation_kwargs: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Any]] = None,
        **kwargs,
    ) -> Dict[str, List[ChatMessage]]:
        # Sanitize messages to avoid Haystack empty message validation errors
        sanitized_messages = []
        for m in messages:
            from haystack.dataclasses import TextContent, ChatMessage

            has_content = (
                getattr(m, "texts", None)
                or getattr(m, "tool_calls", None)
                or getattr(m, "tool_call_results", None)
                or getattr(m, "images", None)
                or getattr(m, "files", None)
            )
            if not has_content:
                # Se un messaggio arriva vuoto (es. filtrato da PII), metti un placeholder
                import logging

                logger = logging.getLogger("aion.lite_llm_adapter")
                logger.warning(
                    f"DEBUG: Dropping empty message with role {m.role} and meta {m.meta}"
                )
                continue  # Drop empty messages entirely instead of polluting the history
            else:
                sanitized_messages.append(m)

        run_params = {
            "messages": sanitized_messages,
            "streaming_callback": streaming_callback,
            "generation_kwargs": generation_kwargs,
            "tools": tools,
        }
        run_params.update(kwargs)

        from src.runtime.llm_call_audit import llm_call_audit_enabled, record_llm_call

        t0 = time.time() if llm_call_audit_enabled() else 0.0

        async def _invoke():
            if hasattr(self.generator, "run_async"):
                run_sig = inspect.signature(self.generator.run_async)
                has_run_kwargs = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in run_sig.parameters.values()
                )
                if has_run_kwargs:
                    filtered_run_params = run_params
                else:
                    filtered_run_params = {
                        k: v for k, v in run_params.items() if k in run_sig.parameters
                    }
                return await self.generator.run_async(**filtered_run_params)
            import asyncio

            run_sig = inspect.signature(self.generator.run)
            has_run_kwargs = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in run_sig.parameters.values()
            )
            if has_run_kwargs:
                filtered_run_params = run_params
            else:
                filtered_run_params = {
                    k: v for k, v in run_params.items() if k in run_sig.parameters
                }
            return await asyncio.to_thread(self.generator.run, **filtered_run_params)

        try:
            result = await _invoke()
        except Exception as exc:
            if llm_call_audit_enabled():
                record_llm_call(
                    self,
                    messages=messages,
                    tools=tools,
                    generation_kwargs=generation_kwargs,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((time.time() - t0) * 1000),
                )
            raise
        if llm_call_audit_enabled():
            record_llm_call(
                self,
                messages=messages,
                tools=tools,
                generation_kwargs=generation_kwargs,
                result=result,
                duration_ms=int((time.time() - t0) * 1000),
            )
        return result

    def to_dict(self) -> Dict[str, Any]:
        from haystack.core.component.serialization import default_to_dict

        return default_to_dict(
            self,
            model=self.model,
            api_base_url=self.api_base_url,
            api_key=self.api_key.to_dict() if self.api_key else None,
            timeout=self.timeout,
            generation_kwargs=self._initial_generation_kwargs,
            tools_strict=self.tools_strict,
            **self.extra_kwargs,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LiteLLMChatGeneratorWrapper":
        from haystack.core.component.serialization import default_from_dict

        if "api_key" in data.get("init_parameters", {}):
            api_key_data = data["init_parameters"]["api_key"]
            if api_key_data:
                data["init_parameters"]["api_key"] = Secret.from_dict(api_key_data)
        return default_from_dict(cls, data)
