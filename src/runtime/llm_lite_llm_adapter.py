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
        run_params = {
            "messages": messages,
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
