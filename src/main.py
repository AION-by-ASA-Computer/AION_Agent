import asyncio
import hashlib
import json
import os
import time
import sys
import logging
import yaml
from collections import OrderedDict
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy import select
from . import aion_env  # noqa: F401 — carica `.env` prima di altri moduli locali

from haystack.tools import Tool
from src.runtime.aion_agent import (
    create_aion_agent,
    ensure_haystack_agent_signatures_valid,
)
from src.runtime.llm_lite_llm_adapter import LiteLLMChatGeneratorWrapper
from haystack.utils import Secret
from .config import config
from .agent_profile import profile_manager
from .runtime.tool_events import tool_event_bus
from .runtime.stream_sync import StreamSync
from .mcp_manager import mcp_manager
from .skill_registry import skill_registry

logger = logging.getLogger(__name__)

from src.runtime.turn_compaction import maybe_compact_after_tool

ensure_haystack_agent_signatures_valid()

# --- HAYSTACK NATIVE REASONING PATCH ---
import haystack.components.generators.chat.openai as openai_module

_orig_convert = openai_module._convert_chat_completion_chunk_to_streaming_chunk


def _patched_convert_chunk(chunk, previous_chunks, component_info=None):
    streaming_chunk = _orig_convert(chunk, previous_chunks, component_info)
    if chunk.choices:
        choice = chunk.choices[0]
        delta = getattr(choice, "delta", None)
        if delta:
            # Aggressive search: vLLM puts it in 'reasoning'
            reasoning = getattr(delta, "reasoning", None) or getattr(
                delta, "reasoning_content", None
            )

            # Pydantic V2 model_extra check for unknown fields
            model_extra = getattr(delta, "model_extra", {}) or {}
            if not reasoning:
                reasoning = model_extra.get("reasoning") or model_extra.get(
                    "reasoning_content"
                )

            if reasoning:
                if "reasoning" not in streaming_chunk.meta:
                    streaming_chunk.meta["reasoning"] = reasoning
    return streaming_chunk


openai_module._convert_chat_completion_chunk_to_streaming_chunk = _patched_convert_chunk

# --- JSON RECOVERY PATCH ---
# Replaces the `json` module reference inside haystack.components.generators.utils
# with a private SimpleNamespace proxy whose `loads` includes automatic repair for
# truncated/malformed LLM tool-call arguments.
#
# Using a proxy instead of mutating json.loads globally means:
#  - Only _gen_utils is affected; all other modules keep the unpatched stdlib loads.
#  - No threading.Lock needed: the substitution is a single import-time assignment.
#  - Compatible with any Haystack 2.x version regardless of function name changes.
try:
    import types as _types
    import json as _json_stdlib
    import haystack.components.generators.utils as _gen_utils

    # Build a proxy that mirrors the json module but with a recovery-aware loads.
    _proxy_json = _types.SimpleNamespace(
        **{
            k: getattr(_json_stdlib, k)
            for k in dir(_json_stdlib)
            if not k.startswith("__")
        }
    )
    _proxy_json.JSONDecodeError = _json_stdlib.JSONDecodeError

    _orig_proxy_loads = (
        _json_stdlib.loads
    )  # capture real loads before any other patching

    def _loads_with_recovery(s, *a, **kw):
        if isinstance(s, str) and len(s) > 1000:
            logger.debug("tool_args_size_large len=%d", len(s))
        try:
            return _orig_proxy_loads(s, *a, **kw)
        except (_json_stdlib.JSONDecodeError, TypeError) as parse_err:
            from .runtime.json_recovery import try_recover_json

            recovered = try_recover_json(s)
            if recovered is not None:
                logger.warning(
                    "json_recovery_used tool_args_len=%d recovered=True",
                    len(s) if isinstance(s, str) else 0,
                )
                return recovered
            logger.error(
                "json_recovery_failed tool_args_len=%d preview=%r parse_err=%s",
                len(s) if isinstance(s, str) else 0,
                (s[:200] if isinstance(s, str) else ""),
                parse_err,
            )
            raise

    _proxy_json.loads = _loads_with_recovery
    # Replace _gen_utils's module-level `json` reference with the proxy.
    # The stdlib json module itself is never mutated.
    _gen_utils.json = _proxy_json
    logger.info(
        "JSON recovery patch applied: haystack.components.generators.utils.json "
        "replaced with proxy (stdlib json.loads unmodified, thread-safe)"
    )
except Exception as e:
    logger.warning("JSON recovery patch non applicabile: %s", e)

for _quiet in (
    "aiosqlite",
    "urllib3",
    "urllib3.connectionpool",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "openai._base_client",
):
    logging.getLogger(_quiet).setLevel(logging.WARNING)

# --- Tool Visibility Bridge ---
# TOOL_EVENT_QUEUE is deprecated, use tool_event_bus
_GLOBAL_LOOP = None
_TOOL_DEDUPE_ENABLED = os.getenv("AION_TOOL_DEDUPE_ENABLED", "1").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_TOOL_DEDUPE_TTL_SEC = float(os.getenv("AION_TOOL_DEDUPE_TTL_SEC", "20"))
_TOOL_DEDUPE_CACHE: Dict[str, tuple[float, bool]] = {}
_MCP_FNAMES_BY_SESSION: Dict[str, set[str]] = {}


def _is_mutating_tool(tool_name: str) -> bool:
    t = (tool_name or "").lower()
    return any(
        k in t
        for k in (
            "create",
            "insert",
            "update",
            "delete",
            "drop",
            "write",
            "edit",
            "remove",
            "install",
            "export",
            "run_python_file",
            "execute",
            "save",
            "mark_",
        )
    )


def _tool_call_fingerprint(
    server_name: str, tool_name: str, session_id: str, kwargs: dict
) -> str:
    payload = dict(kwargs or {})
    payload.pop("_trace_context", None)
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(
        f"{session_id}\0{server_name}\0{tool_name}\0{blob}".encode("utf-8")
    ).hexdigest()


def set_event_loop(loop):
    global _GLOBAL_LOOP
    _GLOBAL_LOOP = loop
    logger.info("Global Event Loop set for AION Bridge.")


def _purge_aion_mcp_tool_functions(session_id: str) -> None:
    """Rimuove wrapper MCP della sessione corrente (non tocca altre chat attive)."""
    fnames = _MCP_FNAMES_BY_SESSION.pop(session_id, set())
    g = sys.modules[__name__].__dict__
    for fname in fnames:
        if fname in g:
            del g[fname]


def _aion_mcp_tool_run(
    server_name: str, tool_name: str, session_id: str, kwargs: dict
) -> str:
    """
    Invocazione MCP serializzabile (funzione top-level, non __call__ su istanza).
    Haystack snapshot/error path chiama Tool.to_dict → serialize_callable.
    """
    import json
    from opentelemetry.propagate import inject

    from .mcp_manager import SerializableMCPTool
    from .runtime.tool_call_ids import new_tool_call_id

    call_id = new_tool_call_id()

    from .runtime.context import get_context
    from .runtime.mcp_tool_result import format_exception_for_tool

    stop_event = get_context().get("stop_event")
    if stop_event and stop_event.is_set():
        return format_exception_for_tool(
            tool_name,
            RuntimeError(
                "Turn cancelled: agent stopped by guard-rail or user interrupt."
            ),
        )

    # Inject OTel trace context for cross-process correlation
    carrier = {}
    inject(carrier)
    kwargs["_trace_context"] = carrier

    loop = _GLOBAL_LOOP or asyncio.get_event_loop()

    # Signal the streaming pipeline that we need to sync before running the tool
    loop.call_soon_threadsafe(
        tool_event_bus.put_event,
        session_id,
        {"type": "request_sync", "tool_name": tool_name},
    )

    # Ensure all preceding text/artifacts from the stream are processed before tool execution
    StreamSync.wait_for_sync(session_id)

    # Re-check stop_event after potentially blocking on StreamSync — cancellation may
    # have been requested during the sync wait.
    if stop_event and stop_event.is_set():
        return format_exception_for_tool(
            tool_name,
            RuntimeError(
                "Turn cancelled: agent stopped by guard-rail or user interrupt."
            ),
        )

    # Agent DB: inject session identity so the LLM cannot omit user_id / tenant / conversation_id.
    if server_name == "agent_db":
        ctx = mcp_manager._session_ctx.get(session_id)
        if ctx:
            if len(ctx) == 3:
                _slug, uid, tid = ctx
            else:
                _slug, uid = ctx
                tid = "default"
            # Hard overwrite to enforce session-bound identity (prevent spoofed payload values).
            kwargs["user_id"] = uid
            kwargs["tenant_id"] = tid
            kwargs["conversation_id"] = session_id

    dedupe_fp: Optional[str] = None
    # Guard against repeated mutating tool calls with identical payload in short window.
    if _TOOL_DEDUPE_ENABLED and _is_mutating_tool(tool_name):
        fp = _tool_call_fingerprint(server_name, tool_name, session_id, kwargs)
        dedupe_fp = fp
        now = time.monotonic()
        stale = [
            k
            for k, (ts, _ok) in _TOOL_DEDUPE_CACHE.items()
            if (now - ts) > _TOOL_DEDUPE_TTL_SEC
        ]
        for k in stale:
            _TOOL_DEDUPE_CACHE.pop(k, None)
        cached = _TOOL_DEDUPE_CACHE.get(fp)
        if cached is not None:
            ts, prev_ok = cached
            if prev_ok and (now - ts) <= _TOOL_DEDUPE_TTL_SEC:
                ttl = int(_TOOL_DEDUPE_TTL_SEC)
                err = RuntimeError(
                    f"Duplicate mutating tool call blocked within {ttl}s; "
                    "change arguments or wait before retry."
                )
                err_body = format_exception_for_tool(tool_name, err)
                loop.call_soon_threadsafe(
                    tool_event_bus.put_event,
                    session_id,
                    {
                        "type": "tool_error",
                        "id": call_id,
                        "name": tool_name,
                        "error": err_body,
                    },
                )
                return err_body

    from .runtime.mcp_tool_args import prepare_mcp_tool_arguments
    from .runtime.mcp_tool_result import classify_tool_result_text
    from .runtime.tool_settlement import settle_tool_call

    prepared, preflight_err = prepare_mcp_tool_arguments(tool_name, kwargs)
    tool_input = prepared if preflight_err is None else kwargs

    from .runtime.sql_query_project_scope import (
        apply_sql_query_project_scope,
        block_project_list_tool,
    )

    if loop is None or loop.is_closed():
        return format_exception_for_tool(
            tool_name,
            RuntimeError(
                "MCP bridge event loop not ready (restart API or retry the turn)."
            ),
        )

    def _emit_tool_outcome(*, is_error: bool, body: str) -> str:
        # SSE/UI first — mid-turn compaction can block 60–90s on the agent thread.
        if is_error:
            loop.call_soon_threadsafe(
                tool_event_bus.put_event,
                session_id,
                {
                    "type": "tool_error",
                    "id": call_id,
                    "name": tool_name,
                    "error": body,
                    "input": tool_input,
                },
            )
            return body
        loop.call_soon_threadsafe(
            tool_event_bus.put_event,
            session_id,
            {
                "type": "tool_end",
                "id": call_id,
                "name": tool_name,
                "output": body,
                "input": tool_input,
            },
        )
        return maybe_compact_after_tool(tool_name=tool_name, result=body)

    settlement_err = settle_tool_call(tool_name, kwargs)
    if settlement_err:
        return _emit_tool_outcome(is_error=True, body=settlement_err)

    list_block = block_project_list_tool(tool_name, session_id)
    if list_block:
        return _emit_tool_outcome(is_error=True, body=list_block)

    prepared = apply_sql_query_project_scope(
        tool_name, prepared if preflight_err is None else kwargs, session_id=session_id
    )
    tool_input = prepared if preflight_err is None else kwargs

    loop.call_soon_threadsafe(
        tool_event_bus.put_event,
        session_id,
        {"type": "tool_start", "id": call_id, "name": tool_name, "input": tool_input},
    )

    if preflight_err:
        _, normalized = classify_tool_result_text(preflight_err, tool_name)
        return _emit_tool_outcome(is_error=True, body=normalized or preflight_err)

    from .runtime.mcp_tool_args import preflight_run_file_tool

    run_preflight = preflight_run_file_tool(tool_name, prepared, session_id)
    if run_preflight:
        return _emit_tool_outcome(is_error=True, body=run_preflight)

    from .runtime.skill_profile_gate import block_skills_hub_tool_if_needed

    skill_block = block_skills_hub_tool_if_needed(
        server_name, tool_name, session_id, prepared
    )
    if skill_block:
        return _emit_tool_outcome(is_error=True, body=skill_block)

    from .runtime.sql_query_memory_gate import (
        block_exploration_tool_if_sql_cache,
        mark_sql_exec_tool_failed,
        mark_sql_exec_tool_used,
    )

    sql_gate = block_exploration_tool_if_sql_cache(
        server_name, tool_name, session_id, prepared
    )
    if sql_gate:
        return _emit_tool_outcome(is_error=True, body=sql_gate)

    from .runtime.datasource_memory_mode import (
        block_list_tables_if_budget_exceeded,
        record_list_tables_call,
    )

    list_budget_block = block_list_tables_if_budget_exceeded(
        server_name, tool_name, session_id
    )
    if list_budget_block:
        return _emit_tool_outcome(is_error=True, body=list_budget_block)

    otel_enabled = os.getenv("AION_OTEL_ENABLED", "0") == "1"
    tracer = None
    if otel_enabled:
        try:
            from opentelemetry import trace

            tracer = trace.get_tracer("aion.mcp")
        except ImportError:
            pass

    profile = "default"
    user_id = "default"
    tenant_id = "default"
    session_ctx = mcp_manager._session_ctx.get(session_id)
    if session_ctx:
        if len(session_ctx) == 3:
            profile, user_id, tenant_id = session_ctx
        else:
            profile, user_id = session_ctx
            tenant_id = "default"

    from contextlib import nullcontext

    span_ctx = nullcontext()
    if tracer:
        try:
            span_ctx = tracer.start_as_current_span(
                f"Profile {profile} tool.execute:{tool_name}"
            )
        except Exception:
            pass

    with span_ctx as span:
        if span and span.is_recording():
            try:
                span.set_attribute("tool.name", tool_name)
                span.set_attribute("tool.mcp_server", server_name)
                span.set_attribute("tool.input", json.dumps(tool_input, default=str))
                span.set_attribute("aion.session_id", session_id)
                span.set_attribute("aion.user_id", user_id)
                span.set_attribute("aion.profile", profile)
                span.set_attribute("aion.tenant_id", tenant_id)
            except Exception:
                pass

        if loop.is_running():
            try:
                from src.runtime.hooks import HookContext, hook_registry

                pre_ctx = HookContext(
                    event="pre_tool_use",
                    tenant_id=tenant_id,
                    conversation_id=session_id,
                    user_id=user_id,
                    profile=profile,
                    payload={
                        "tool_name": tool_name,
                        "server_name": server_name,
                        "input": tool_input,
                    },
                )
                asyncio.run_coroutine_threadsafe(
                    hook_registry.dispatch("pre_tool_use", pre_ctx), loop
                )
            except Exception as hook_err:
                logger.warning("Failed to dispatch pre_tool_use hook: %s", hook_err)

        mcp_t0 = time.monotonic()
        try:
            result = SerializableMCPTool(server_name, tool_name, session_id)(**prepared)
            try:
                data = json.loads(result)
                if isinstance(data, dict) and "data" in data and "query" in data:
                    from src.chart_queue import chart_queue

                    chart_queue.push_serialized(session_id, data)
                    result = f"[Grafico generato con successo per la query: {data.get('query')}]"
            except Exception:
                pass
            is_err, normalized = classify_tool_result_text(str(result), tool_name)
            if is_err:
                mark_sql_exec_tool_failed(session_id, tool_name)
            else:
                mark_sql_exec_tool_used(session_id, tool_name)
                base = (tool_name or "").split("-")[-1].strip().lower()
                if base in ("list_tables", "list_schemas"):
                    record_list_tables_call(session_id)
                elif base in (
                    "execute_sql",
                    "query",
                    "run_sql",
                    "sql_query",
                    "mysql_query",
                    "postgres_query",
                ):
                    from .runtime.sql_query_memory_context import (
                        get_sql_qm_turn_context,
                        record_last_success,
                    )
                    from .memory.sql_query_memory.fingerprint import (
                        extract_schemas_from_sql,
                        extract_tables_from_sql,
                    )

                    sql_text = ""
                    if isinstance(prepared, dict):
                        sql_text = str(
                            prepared.get("sql")
                            or prepared.get("query")
                            or prepared.get("statement")
                            or ""
                        )
                    if sql_text:
                        record_last_success(
                            session_id,
                            sql_text=sql_text,
                            schemas=extract_schemas_from_sql(sql_text),
                            tables=extract_tables_from_sql(sql_text),
                        )
                    from .runtime.sql_query_memory_context import (
                        increment_cache_hits_sync,
                    )

                    increment_cache_hits_sync(session_id)
            logger.info(
                "MCP tool %s/%s finished in %.2fs (error=%s)",
                server_name,
                tool_name,
                time.monotonic() - mcp_t0,
                is_err,
            )

            if span and span.is_recording():
                try:
                    span.set_attribute(
                        "tool.status", "success" if not is_err else "error"
                    )
                    span.set_attribute("tool.output", str(normalized))
                except Exception:
                    pass

            if loop.is_running():
                try:
                    from src.runtime.hooks import HookContext, hook_registry

                    post_ctx = HookContext(
                        event="post_tool_use",
                        tenant_id=tenant_id,
                        conversation_id=session_id,
                        user_id=user_id,
                        profile=profile,
                        payload={
                            "tool_name": tool_name,
                            "server_name": server_name,
                            "input": tool_input,
                            "status": "error" if is_err else "success",
                        },
                    )
                    asyncio.run_coroutine_threadsafe(
                        hook_registry.dispatch("post_tool_use", post_ctx), loop
                    )
                except Exception as hook_err:
                    logger.warning(
                        "Failed to dispatch post_tool_use hook: %s", hook_err
                    )

            if dedupe_fp and not is_err:
                _TOOL_DEDUPE_CACHE[dedupe_fp] = (time.monotonic(), True)
            return _emit_tool_outcome(is_error=is_err, body=normalized)
        except Exception as e:
            logger.warning(
                "MCP tool %s/%s failed in %.2fs: %s",
                server_name,
                tool_name,
                time.monotonic() - mcp_t0,
                e,
            )
            err_text = format_exception_for_tool(tool_name, e)
            if isinstance(e, TimeoutError):
                pg_cap = os.getenv("AION_PG_QUERY_TIMEOUT_SEC", "60")
                err_text = format_exception_for_tool(
                    tool_name,
                    TimeoutError(
                        f"Query timed out ({server_name}/{tool_name}). "
                        f"PostgreSQL cap AION_PG_QUERY_TIMEOUT_SEC={pg_cap}s; "
                        f"MCP bridge cap AION_MCP_TOOL_RESULT_TIMEOUT="
                        f"{os.getenv('AION_MCP_TOOL_RESULT_TIMEOUT', '120')}s. "
                        "Heavy JOINs may need indexes or a narrower filter (e.g. codice_ditta). "
                        "The MCP worker was recycled; retry with a simpler query."
                    ),
                )
            mark_sql_exec_tool_failed(session_id, tool_name)

            if span and span.is_recording():
                try:
                    from opentelemetry.trace import Status, StatusCode

                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.set_attribute("tool.status", "error")
                    span.set_attribute("tool.error", str(e))
                except Exception:
                    pass

            if loop.is_running():
                try:
                    from src.runtime.hooks import HookContext, hook_registry

                    post_ctx = HookContext(
                        event="post_tool_use",
                        tenant_id=tenant_id,
                        conversation_id=session_id,
                        user_id=user_id,
                        profile=profile,
                        payload={
                            "tool_name": tool_name,
                            "server_name": server_name,
                            "input": tool_input,
                            "status": "error",
                            "error": str(e),
                        },
                    )
                    asyncio.run_coroutine_threadsafe(
                        hook_registry.dispatch("post_tool_use", post_ctx), loop
                    )
                except Exception as hook_err:
                    logger.warning(
                        "Failed to dispatch post_tool_use hook: %s", hook_err
                    )

            return _emit_tool_outcome(is_error=True, body=err_text)


def _register_mcp_tool_function(server_name: str, tool_name: str, session_id: str):
    """
    Registra nel modulo una funzione top-level `aion_mcp_x_<hash>(**kwargs)` che delega a _aion_mcp_tool_run.
    """
    h = hashlib.sha256(
        f"{server_name}\0{tool_name}\0{session_id}".encode("utf-8")
    ).hexdigest()[:24]
    fname = f"aion_mcp_x_{h}"
    g = sys.modules[__name__].__dict__
    if fname in g and callable(g[fname]):
        return g[fname]
    code = compile(
        f"def {fname}(**kwargs):\n"
        f"    return _aion_mcp_tool_run({server_name!r}, {tool_name!r}, {session_id!r}, kwargs)\n",
        __file__,
        "exec",
    )
    exec(code, g)
    _MCP_FNAMES_BY_SESSION.setdefault(session_id, set()).add(fname)
    return g[fname]


async def build_mcp_tools(
    name: str, server_config: Dict[str, Any], session_id: str, user_id: str = "default"
):
    """Discovers tools from an MCP server using the manager and optional sandboxing."""
    discovered_tools = []

    missing = mcp_manager.stdio_entrypoint_missing(name, server_config)
    if missing:
        logger.warning("MCP server %s skipped: %s", name, missing)
        try:
            from .runtime.mcp_health import record_mcp_load_error

            record_mcp_load_error(session_id, name, missing)
        except Exception:
            pass
        return discovered_tools

    if (
        server_config.get("type") or ""
    ).lower() == "in_process" and name == "orchestration":
        from .runtime.orchestration_tools import build_orchestration_haystack_tools

        return build_orchestration_haystack_tools(session_id, user_id)

    try:
        list_timeout = float(os.getenv("AION_MCP_LIST_TOOLS_TIMEOUT_SEC", "30"))
        # Session-scoped pool: stesso stdio per tutta la chat (AION_MCP_POOL=1)
        async with mcp_manager.session_context(
            name, chat_session_id=session_id
        ) as session:
            tools_result = await asyncio.wait_for(
                session.list_tools(), timeout=list_timeout
            )

        for mcp_tool in tools_result.tools:
            fn = _register_mcp_tool_function(name, mcp_tool.name, session_id)
            haystack_tool = Tool(
                name=mcp_tool.name,
                description=mcp_tool.description or f"MCP Tool: {mcp_tool.name}",
                function=fn,
                parameters=mcp_tool.inputSchema,
            )
            discovered_tools.append(haystack_tool)

        logger.info(f"✅ Discovered {len(discovered_tools)} tools from {name}")
        logger.info(
            "mcp_tools_discovered server=%s count=%d tools=%s",
            name,
            len(discovered_tools),
            [t.name for t in discovered_tools],
        )
    except Exception as e:
        err = str(e).strip() or type(e).__name__
        logger.error("❌ Handshake FAILED for %s: %s", name, err)
        try:
            from .runtime.mcp_health import record_mcp_load_error

            record_mcp_load_error(session_id, name, err)
        except Exception:
            pass

    return discovered_tools


_AGENT_CACHE: "OrderedDict[str, Tuple[Any, str]]" = OrderedDict()
_AGENT_CACHE_LOCK = asyncio.Lock()
_AGENT_BUILD_INFLIGHT: Dict[str, asyncio.Future] = {}
_AGENT_CACHE_MAX = int(os.getenv("AION_AGENT_CACHE_MAX", "256"))
_AGENT_CACHE_ENABLED = os.getenv("AION_AGENT_CACHE", "1").lower() in (
    "1",
    "true",
    "yes",
)


def clear_agent_cache() -> None:
    """Drop cached agents (e.g. after LLM provider or token limit changes)."""
    _AGENT_CACHE.clear()
    _AGENT_BUILD_INFLIGHT.clear()
    logger.info("Agent cache cleared")


def _build_chat_generation_kwargs() -> Tuple[Dict[str, Any], str]:
    """
    Haystack/OpenAI SDK: vLLM vendor fields go in ``extra_body`` (not all builds accept
    top-level ``thinking_token_budget`` on the Python client).

    See vLLM "Reasoning outputs" (thinking_token_budget) and OpenAI SDK ``extra_body``.
    Returns (generation_kwargs dict, stable fragment for agent cache key).
    """
    gen_kw: Dict[str, Any] = {}
    _max_chat = os.getenv("AION_CHAT_MAX_TOKENS", "8192").strip()
    try:
        if _max_chat:
            gen_kw["max_tokens"] = int(_max_chat)
    except ValueError:
        logger.warning("AION_CHAT_MAX_TOKENS non numerico, ignorato")

    extra: Dict[str, Any] = {}
    raw_extra = (os.getenv("AION_VLLM_EXTRA_BODY") or "").strip()
    if raw_extra:
        try:
            parsed = json.loads(raw_extra)
            if isinstance(parsed, dict):
                extra.update(parsed)
            else:
                logger.warning(
                    "AION_VLLM_EXTRA_BODY deve essere un oggetto JSON, ignorato"
                )
        except json.JSONDecodeError as e:
            logger.warning("AION_VLLM_EXTRA_BODY JSON non valido: %s", e)

    # Solo se impostato esplicitamente: vLLM richiede --reasoning-config insieme al budget
    # (altrimenti: "thinking_token_budget is set but reasoning_config is not configured").
    budget_raw = (os.getenv("AION_THINKING_TOKEN_BUDGET") or "").strip()
    if budget_raw.lower() not in ("", "0", "false", "no", "off"):
        try:
            tb = int(budget_raw)
            if tb > 0:
                extra.setdefault("thinking_token_budget", tb)
        except ValueError:
            logger.warning("AION_THINKING_TOKEN_BUDGET non numerico, ignorato")

    if extra:
        gen_kw["extra_body"] = extra

    sig = json.dumps(extra, sort_keys=True, separators=(",", ":")) if extra else ""
    cache_sig = f"{_max_chat}\v{sig}"
    return gen_kw, cache_sig


async def build_all_tools(session_id: str, profile, user_id: str = "default"):
    """Build tools: delegation legacy, tool nativi da registry, poi MCP."""
    from .runtime.orchestration_tools import (
        ORCHESTRATION_BUILTIN_SERVER,
        merge_builtin_orchestration_tools,
    )
    from .runtime.cron_tools import CRON_BUILTIN_SERVER, merge_builtin_cron_tools

    _purge_aion_mcp_tool_functions(session_id)
    all_tools = []

    if "aion_subagents" in profile.mcp_servers:
        from .runtime.subagent_tools import get_delegation_tool

        all_tools.append(get_delegation_tool(session_id, user_id))

    from .runtime.native_tools import load_native_tools

    all_tools.extend(load_native_tools(profile, session_id, user_id))

    from .runtime.settlement_tool_registry import build_settlement_tools

    all_tools.extend(build_settlement_tools())

    from .data.engine import get_async_session_maker
    from .data.models import McpServerConfig
    from sqlalchemy import select

    skip_slugs: set[str] = set()
    try:
        from .runtime.mcp_integration_helpers import (
            get_user_mcp_preference_map,
            user_mcp_effective_active,
        )

        tenant = (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip()
        pref_map = await get_user_mcp_preference_map(user_id, tenant_id=tenant)
        async with get_async_session_maker()() as session:
            cfg_rows = (
                (
                    await session.execute(
                        select(McpServerConfig).where(
                            McpServerConfig.server_slug.in_(profile.mcp_servers or [])
                        )
                    )
                )
                .scalars()
                .all()
            )
        policy_by_slug = {r.server_slug: r for r in cfg_rows}
        for server_name in profile.mcp_servers or []:
            pol = policy_by_slug.get(server_name)
            if pol and not user_mcp_effective_active(
                server_name,
                pref_map=pref_map,
                user_may_disable=bool(getattr(pol, "user_may_disable", True)),
            ):
                skip_slugs.add(server_name)
    except Exception as ex:
        logger.debug("MCP user preference filter skipped: %s", ex)

    try:
        profile_slugs = set(profile.mcp_servers or [])
        async with get_async_session_maker()() as session:
            enabled_rows = (
                (
                    await session.execute(
                        select(McpServerConfig.server_slug).where(
                            McpServerConfig.is_enabled_for_users.is_(True)
                        )
                    )
                )
                .scalars()
                .all()
            )
        for slug in enabled_rows:
            if (
                slug
                and slug not in profile_slugs
                and mcp_manager.get_server_config(slug)
            ):
                if slug in (ORCHESTRATION_BUILTIN_SERVER, CRON_BUILTIN_SERVER):
                    continue
                logger.warning(
                    "MCP '%s' abilitato in chat ma assente da profile.mcp_servers (%s); "
                    "aggiungilo al profilo per esporre i tool all'agente.",
                    slug,
                    profile.name,
                )
    except Exception as ex:
        logger.debug("MCP profile/integration check skipped: %s", ex)

    mcp_discover_names = [
        server_name
        for server_name in profile.mcp_servers or []
        if server_name not in (ORCHESTRATION_BUILTIN_SERVER, CRON_BUILTIN_SERVER)
        and server_name not in skip_slugs
    ]

    async def _discover_mcp_server(server_name: str) -> list:
        server_config = mcp_manager.get_server_config(server_name)
        if not server_config:
            logger.warning(
                f"MCP Server '{server_name}' requested but not found in registry."
            )
            return []
        return await build_mcp_tools(
            server_name, server_config, session_id, user_id=user_id
        )

    if mcp_discover_names:
        discovered_batches = await asyncio.gather(
            *[_discover_mcp_server(name) for name in mcp_discover_names],
            return_exceptions=True,
        )
        for server_name, batch in zip(
            mcp_discover_names, discovered_batches, strict=True
        ):
            if isinstance(batch, Exception):
                err = str(batch).strip() or type(batch).__name__
                logger.error("MCP discovery failed for %s: %s", server_name, err)
                try:
                    from .runtime.mcp_health import record_mcp_load_error

                    record_mcp_load_error(session_id, server_name, err)
                except Exception:
                    pass
                continue
            all_tools.extend(batch)

    merge_builtin_orchestration_tools(all_tools, session_id, user_id)
    merge_builtin_cron_tools(all_tools, session_id, user_id)
    from .runtime.deep_research_tools import merge_builtin_deep_research_tools

    merge_builtin_deep_research_tools(all_tools, session_id, user_id, profile)
    from .runtime.sql_query_memory_tools import merge_builtin_sql_query_memory_tools

    merge_builtin_sql_query_memory_tools(all_tools, session_id, user_id, profile)
    logger.debug(
        "Built-in orchestration/cron tools merged for session=%s (profile=%s)",
        session_id[:8] + "..." if len(session_id) > 8 else session_id,
        getattr(profile, "name", "?"),
    )

    return all_tools


def _skills_content_hash(skill_names: list) -> str:
    """Hash contenuto skill per invalidare _AGENT_CACHE quando cambiano i file .md."""
    import hashlib

    from .runtime.skill_alias import resolve_skill_alias

    pieces = []
    for name in sorted(skill_names or []):
        actual = resolve_skill_alias(name)
        body = skill_registry.get_skill_full(actual) or ""
        pieces.append(f"{actual}:{hashlib.md5(body.encode()).hexdigest()[:8]}")
    return hashlib.md5("|".join(pieces).encode()).hexdigest()[:16]


async def get_agent(
    profile_name: str = "aion_std",
    session_id: str = "default",
    user_id: str = "default",
    tenant_id: str = "default",
    agent_mode: str = "normal",
    plan_mode: Optional[bool] = None,
    message_source: str = "user_input",
    llm_provider_name: Optional[str] = None,
):
    """
    Agent Factory: Carica il profilo, le skill e i tool MCP dinamicamente.
    Con AION_AGENT_CACHE=1 riusa agente + tool discovery per la stessa tripletta
    (session_id, profilo, user_id) così i worker MCP restano caldi e non si ripete il log di init.
    """
    logger.info(
        "agent_build_start profile=%s session=%s user=%s",
        profile_name,
        session_id,
        user_id,
    )
    from .agent_profile import ProfileNotFoundError

    try:
        if user_id and user_id != "default":
            from sqlalchemy import select
            from .data.engine import get_async_session_maker
            from .data.models import UserProfileAccess

            async with get_async_session_maker()() as session:
                q = select(UserProfileAccess.profile_slug).where(
                    UserProfileAccess.user_id == user_id
                )
                res = await session.execute(q)
                allowed_slugs = [r[0] for r in res.all()]

            if allowed_slugs:
                try:
                    resolved_p = profile_manager.resolve_profile(profile_name)
                    resolved_slug = resolved_p.slug
                except ProfileNotFoundError:
                    resolved_slug = profile_name

                if resolved_slug not in allowed_slugs:
                    if resolved_slug == "aion_std":
                        profile_name = allowed_slugs[0]
                        logger.info(
                            "Default profile aion_std not allowed. Falling back to %s for user %s",
                            profile_name,
                            user_id,
                        )
                    else:
                        logger.warning(
                            "User %s denied access to profile %s",
                            user_id,
                            resolved_slug,
                        )
                        raise ProfileNotFoundError(profile_name, allowed_slugs)

        profile = profile_manager.resolve_profile(profile_name)
    except ProfileNotFoundError:
        raise

    skill_registry.reload_if_stale()

    from src.runtime.user_language import load_user_ui_language

    user_lang = await load_user_ui_language(user_id)

    from .runtime.native_tools import native_registry_content_hash

    gen_kw, gen_cache_sig = _build_chat_generation_kwargs()
    nt_groups = ",".join(getattr(profile, "native_tool_groups", None) or [])
    profile_sig = (
        ",".join(profile.mcp_servers)
        + "|"
        + ",".join(profile.skills or [])
        + "|nt:"
        + nt_groups
        + "|ntr:"
        + native_registry_content_hash()
    )
    skills_hash = _skills_content_hash(profile.skills or [])
    skill_prompt_mode = os.getenv("AION_SKILL_SYSTEM_PROMPT_MODE", "index").lower()
    critical_sig = ",".join(sorted(profile._resolved_critical_skill_names()))

    from src.runtime.agent_mode_resolve import resolve_agent_mode

    resolved_agent_mode = resolve_agent_mode(
        agent_mode,
        plan_mode,
        message_source=message_source,
    )
    # Env default (e.g. AION_DEFAULT_AGENT_MODE=plan) only for real user turns — not post-approval execution.
    if (message_source or "user_input").strip() in ("user_input",):
        env_default_mode = (
            (os.getenv("AION_DEFAULT_AGENT_MODE") or "normal").strip().lower()
        )
        if resolved_agent_mode == "normal" and env_default_mode in (
            "plan",
            "ask",
            "debug",
            "deep_research",
        ):
            resolved_agent_mode = env_default_mode

    cache_key = (
        f"{session_id}\0{profile.slug}\0{profile_sig}\0{user_id}\0{tenant_id}"
        f"\0{gen_cache_sig}\0{skills_hash}\0{skill_prompt_mode}\0{critical_sig}"
        f"\0{user_lang or ''}\0{resolved_agent_mode}\0{llm_provider_name or ''}"
    )
    build_waiter: Optional[asyncio.Future] = None
    build_leader = False
    if _AGENT_CACHE_ENABLED:
        async with _AGENT_CACHE_LOCK:
            hit = _AGENT_CACHE.get(cache_key)
            if hit is not None:
                _AGENT_CACHE.move_to_end(cache_key)
                logger.debug(
                    "get_agent: cache hit session=%s profile=%s mode=%s",
                    session_id[:8] + "...",
                    profile.slug,
                    resolved_agent_mode,
                )
                return hit
            build_waiter = _AGENT_BUILD_INFLIGHT.get(cache_key)
            if build_waiter is None:
                build_waiter = asyncio.get_running_loop().create_future()
                _AGENT_BUILD_INFLIGHT[cache_key] = build_waiter
                build_leader = True
        if not build_leader:
            logger.debug(
                "get_agent: await in-flight build session=%s profile=%s",
                session_id[:8] + "...",
                profile.slug,
            )
            return await build_waiter

    try:
        return await _finish_get_agent_build(
            cache_key=cache_key,
            build_waiter=build_waiter,
            build_leader=build_leader,
            session_id=session_id,
            profile=profile,
            user_id=user_id,
            tenant_id=tenant_id,
            resolved_agent_mode=resolved_agent_mode,
            user_lang=user_lang,
            gen_kw=gen_kw,
            skill_prompt_mode=skill_prompt_mode,
            llm_provider_name=llm_provider_name,
        )
    except BaseException as exc:
        if build_leader and build_waiter is not None and not build_waiter.done():
            build_waiter.set_exception(exc)
        raise
    finally:
        if build_leader:
            async with _AGENT_CACHE_LOCK:
                if _AGENT_BUILD_INFLIGHT.get(cache_key) is build_waiter:
                    _AGENT_BUILD_INFLIGHT.pop(cache_key, None)


async def _finish_get_agent_build(
    *,
    cache_key: str,
    build_waiter: Optional[asyncio.Future],
    build_leader: bool,
    session_id: str,
    profile: Any,
    user_id: str,
    tenant_id: str,
    resolved_agent_mode: str,
    user_lang: Optional[str],
    gen_kw: Dict[str, Any],
    skill_prompt_mode: str,
    llm_provider_name: Optional[str] = None,
) -> Tuple[Any, str]:
    # Pre-avvio MCP stdio del profilo (pool per sessione), poi discovery tool
    await mcp_manager.warm_session(
        session_id,
        profile.mcp_servers,
        profile_slug=profile.slug,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    tools = await build_all_tools(session_id, profile, user_id=user_id)

    # 5. Plan Mode: rimuovi fisicamente i tool mutanti dalla lista passata al LLM.
    # Il blocco avviene a livello di protocollo (il LLM non vede i tool nella sua context window),
    # non solo per direttiva nel prompt. La lista è configurabile via AION_PLAN_MODE_BLOCKED_TOOLS.
    if resolved_agent_mode == "plan":
        from src.runtime.plan_mode import (
            PLAN_MODE_DRAFT_TOOL_NAMES,
            effective_plan_mode_blocked_tool_names,
            plan_mode_blocked_tool_names,
            plan_mode_tool_first,
        )

        _blocked_names = effective_plan_mode_blocked_tool_names()
        if plan_mode_tool_first():
            _overridden = plan_mode_blocked_tool_names() & set(
                PLAN_MODE_DRAFT_TOOL_NAMES
            )
            if _overridden:
                logger.warning(
                    "Plan Mode tool-first: ignoring AION_PLAN_MODE_BLOCKED_TOOLS for %s",
                    ", ".join(sorted(_overridden)),
                )
        if _blocked_names:
            allowed_tools: list = []
            removed_names: list[str] = []
            for t in tools:
                if getattr(t, "name", None) in _blocked_names:
                    removed_names.append(t.name)
                else:
                    allowed_tools.append(t)
            tools = allowed_tools
            if removed_names:
                logger.info(
                    "🔒 Plan Mode: rimossi %d tool mutanti dalla lista agente: %s",
                    len(removed_names),
                    ", ".join(sorted(removed_names)),
                )
    elif resolved_agent_mode == "deep_research":
        from src.runtime.deep_research_mode import deep_research_blocked_tool_names

        _blocked_names = deep_research_blocked_tool_names()
        if _blocked_names:
            allowed_tools = []
            removed_names = []
            for t in tools:
                if getattr(t, "name", None) in _blocked_names:
                    removed_names.append(t.name)
                else:
                    allowed_tools.append(t)
            tools = allowed_tools
            if removed_names:
                logger.info(
                    "🔒 Deep Research Mode: rimossi %d tool dalla lista agente: %s",
                    len(removed_names),
                    ", ".join(sorted(removed_names)),
                )

    from .runtime.sql_query_memory_tools import profile_wants_sql_query_memory

    if profile_wants_sql_query_memory(profile):
        from .runtime.datasource_memory_mode import datasource_blocked_promql_tool_names

        blocked_promql = datasource_blocked_promql_tool_names()
        native_sql_names = {
            "sql_memory_search",
            "sql_memory_save",
            "sql_memory_list_projects",
            "sql_memory_list_saved",
        }
        mcp_sql_dupes = {
            "search_known_sql",
            "save_successful_sql",
            "list_sql_projects",
            "mark_sql_query_successful",
        }
        has_native_sql = any(
            getattr(t, "name", None) in native_sql_names for t in tools
        )
        filtered_tools: list = []
        removed_datasource: list[str] = []
        for t in tools:
            name = getattr(t, "name", None) or ""
            base = name.split("-")[-1].strip().lower()
            if base in blocked_promql:
                removed_datasource.append(name)
                continue
            if has_native_sql and base in mcp_sql_dupes:
                removed_datasource.append(name)
                continue
            filtered_tools.append(t)
        if removed_datasource:
            logger.info(
                "Datasource profile: removed %d PromQL/duplicate memory tools: %s",
                len(removed_datasource),
                ", ".join(sorted(removed_datasource)),
            )
        tools = filtered_tools

    from src.runtime.artifact_tool_policy import stream_artifact_tools_blocked

    _artifact_blocked = stream_artifact_tools_blocked()
    if _artifact_blocked:
        kept: list = []
        removed_artifact: list[str] = []
        for t in tools:
            name = getattr(t, "name", None) or ""
            base = name.split("-")[-1].strip().lower()
            if name in _artifact_blocked or base in _artifact_blocked:
                removed_artifact.append(name)
            else:
                kept.append(t)
        if removed_artifact:
            logger.info(
                "Artifact protocol: removed write tool(s): %s",
                ", ".join(sorted(removed_artifact)),
            )
        tools = kept

    # 1. Resolve LLM Configuration from Environment
    from src.runtime.llm_adapter import (
        normalize_litellm_provider,
        resolve_llm_adapter,
        resolve_llm_endpoint,
        resolve_llm_timeout,
    )

    llm_url, llm_model = resolve_llm_endpoint()
    llm_adapter = resolve_llm_adapter()
    logger.info("LLM adapter: %s", llm_adapter)
    llm_timeout = resolve_llm_timeout()

    logger.info(
        f"🚀 Initializing Generator: {llm_model} at {llm_url} Provider: {llm_provider_name} (Timeout: {llm_timeout}s, Mode: {resolved_agent_mode})"
    )
    eb = gen_kw.get("extra_body")
    if isinstance(eb, dict) and eb.get("thinking_token_budget") is not None:
        logger.info(
            "vLLM thinking_token_budget=%s (extra_body); server deve avere --reasoning-config "
            "e --reasoning-parser qwen3",
            eb.get("thinking_token_budget"),
        )

    tools_strict_raw = os.getenv("AION_TOOLS_STRICT", "1").strip().lower()
    tools_strict = tools_strict_raw in ("1", "true", "yes", "on")
    # Local vLLM/OpenAI-compatible servers often emit truncated tool JSON with strict mode.
    _llm_url_l = (llm_url or "").lower()
    if tools_strict and any(
        x in _llm_url_l for x in ("localhost", "127.0.0.1", "192.168.", "10.", "172.")
    ):
        if os.getenv("AION_VLLM_TOOLS_STRICT", "0").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            tools_strict = False
            logger.info(
                "tools_strict disabled for local LLM endpoint (set AION_VLLM_TOOLS_STRICT=1 to force)"
            )

    provider_loaded = False
    row = None
    # Se llm_provider_name è specificato, carica il provider dal database
    if llm_provider_name:
        logger.info("Caricamento provider LLM dal database: %s", llm_provider_name)
        from src.api.llm_providers import LlmProviderPublic
        from src.data.engine import get_async_session_maker
        from src.data.models import LlmProvider
        from src.runtime.credential_store import decrypt_value

        async with get_async_session_maker()() as session:
            row = (
                (
                    await session.execute(
                        select(LlmProvider).where(
                            LlmProvider.tenant_id == "default",
                            LlmProvider.slug == llm_provider_name,
                        )
                    )
                )
                .scalars()
                .first()
            )
        if row:
            if not row.enabled:
                logger.warning(
                    "Provider LLM %s è disattivato, uso configurazione env",
                    llm_provider_name,
                )
            else:
                provider_api_base = row.api_base_url
                litellm_provider = normalize_litellm_provider(
                    row.provider, provider_api_base
                )
                provider_model = (
                    f"{litellm_provider}/{row.model_name}"
                    if "/" not in row.model_name
                    else row.model_name
                )
                provider_timeout = row.timeout
                if row.api_key_encrypted:
                    api_key = decrypt_value(row.api_key_encrypted)
                    api_key_secret = Secret.from_token(api_key)
                else:
                    api_key_secret = Secret.from_token(
                        os.getenv("AION_LLM_API_KEY", "placeholder-token")
                    )

                # extra_body è vLLM/OpenAI-specific — va rimosso per provider che non lo supportano
                provider_gen_kw = None
                if gen_kw:
                    provider_gen_kw = {
                        k: v for k, v in gen_kw.items() if k != "extra_body"
                    }
                    if row.thinking_token_budget:
                        if row.provider in ("openai", "azure"):
                            eb = provider_gen_kw.get("extra_body") or {}
                            eb["thinking_token_budget"] = row.thinking_token_budget
                            provider_gen_kw["extra_body"] = eb
                        elif row.provider in ("anthropic", "google"):
                            budget = row.thinking_token_budget
                            provider_gen_kw["thinking"] = {
                                "type": "enabled",
                                "budget_tokens": budget,
                            }
                            max_tokens = row.max_chat_tokens or 8192
                            if max_tokens <= budget:
                                max_tokens = budget + 2048
                            provider_gen_kw["max_tokens"] = max_tokens
                elif row.thinking_token_budget:
                    provider_gen_kw = {}
                    if row.provider in ("openai", "azure"):
                        provider_gen_kw["extra_body"] = {
                            "thinking_token_budget": row.thinking_token_budget
                        }
                    elif row.provider in ("anthropic", "google"):
                        budget = row.thinking_token_budget
                        provider_gen_kw["thinking"] = {
                            "type": "enabled",
                            "budget_tokens": budget,
                        }
                        max_tokens = row.max_chat_tokens or 8192
                        if max_tokens <= budget:
                            max_tokens = budget + 2048
                        provider_gen_kw["max_tokens"] = max_tokens

                if row.max_chat_tokens is not None:
                    if provider_gen_kw is None:
                        provider_gen_kw = {}
                    max_out = row.max_chat_tokens
                    if row.thinking_token_budget and row.provider in (
                        "anthropic",
                        "google",
                    ):
                        budget = row.thinking_token_budget
                        if max_out <= budget:
                            max_out = budget + 2048
                    elif row.thinking_token_budget and row.provider in (
                        "openai",
                        "azure",
                    ):
                        # vLLM/Qwen: tool-call JSON (write/edit) needs a large completion budget
                        # separate from thinking_token_budget; DB max_chat_tokens is often too low.
                        try:
                            floor = int(
                                os.getenv("AION_VLLM_TOOL_ARG_TOKEN_FLOOR", "8192")
                            )
                        except ValueError:
                            floor = 8192
                        if max_out < floor:
                            max_out = floor
                            logger.info(
                                "max_tokens raised %d -> %d for vLLM provider %s "
                                "(thinking_token_budget=%s; tool-arg floor)",
                                row.max_chat_tokens,
                                max_out,
                                row.slug,
                                row.thinking_token_budget,
                            )
                    provider_gen_kw["max_tokens"] = max_out

                chat_generator = LiteLLMChatGeneratorWrapper(
                    api_base_url=provider_api_base,
                    model=provider_model,
                    timeout=provider_timeout,
                    api_key=api_key_secret,
                    generation_kwargs=provider_gen_kw,
                    tools_strict=tools_strict,
                )
                logger.info(
                    "Using LiteLLMChatGeneratorWrapper for model: %s (provider: %s, stored: %s)",
                    provider_model,
                    litellm_provider,
                    row.provider,
                )
                provider_loaded = True

                logger.info(
                    "Provider LLM caricato: %s (%s/%s)",
                    row.display_name,
                    row.provider,
                    row.model_name,
                )
        else:
            # Provider non trovato, uso configurazione env
            logger.info(
                "Provider LLM %s non trovato, uso configurazione env", llm_provider_name
            )

    # Fallback: crea chat_generator dalla configurazione env se non già caricato dal DB
    if not provider_loaded:
        api_key_secret = Secret.from_token(
            os.getenv("AION_LLM_API_KEY", "placeholder-token")
        )
        chat_generator = LiteLLMChatGeneratorWrapper(
            api_base_url=llm_url,
            model=llm_model,
            timeout=llm_timeout,
            api_key=api_key_secret,
            generation_kwargs=gen_kw if gen_kw else None,
            tools_strict=tools_strict,
        )
        logger.info(
            "Using env-based LiteLLMChatGeneratorWrapper for model: %s", llm_model
        )

    # 3. Inizializza l'Agente Haystack (skill: index o full via AION_SKILL_SYSTEM_PROMPT_MODE)
    _prompt_provider = ""
    _prompt_model = llm_model
    if provider_loaded and row is not None:
        _prompt_provider = str(getattr(row, "provider", "") or "")
        _prompt_model = str(getattr(row, "model_name", "") or llm_model)
    system_prompt = profile.generate_system_prompt(
        user_id=user_id,
        provider=_prompt_provider,
        model_id=_prompt_model,
    )
    if user_lang:
        from src.runtime.user_language import build_ui_language_prompt_section

        system_prompt += build_ui_language_prompt_section(user_lang)

    # 4. Mode-specific prompts dynamically injected
    if resolved_agent_mode == "plan":
        from src.runtime.plan_mode import build_plan_mode_system_prompt

        system_prompt += build_plan_mode_system_prompt()
    elif resolved_agent_mode == "deep_research":
        from src.runtime.deep_research_mode import build_deep_research_system_prompt

        system_prompt += build_deep_research_system_prompt()
    elif resolved_agent_mode == "ask":
        system_prompt += (
            "\n\n## ASK MODE (clarification / Q&A)\n"
            "You are in ASK MODE. Answer questions, explain code, and discuss technical details "
            "without making write changes or running mutating commands unless the user explicitly "
            "asks for a theoretical example.\n"
            "Rules:\n"
            "1. Answer clearly and thoroughly.\n"
            "2. Do not propose or start code edits or command execution unless asked for explanation only."
        )
    elif resolved_agent_mode == "debug":
        system_prompt += (
            "\n\n## DEBUG MODE (error resolution)\n"
            "You are in DEBUG MODE. Analyze error logs, trace bugs, and verify reported failures.\n"
            "Rules:\n"
            "1. Examine code and logs carefully to find root cause.\n"
            "2. Explain fixes in detail before applying changes.\n"
            "3. Understand the problem fully before rushing corrective actions."
        )

    # Datasource workflow lives in skill `datasource_memory_protocol` (critical_skills);
    # avoid duplicating the same 6-step block via runtime overlay.

    # === OPIK TELEMETRY WRAPPERS ===
    try:
        from src.observability.opik_setup import OPIK_AVAILABLE

        if OPIK_AVAILABLE:
            import functools
            from opik import track
            from opik.opik_context import update_current_span

            # Wrap OpenAIChatGenerator.run to trace LLM calls while preserving signature
            original_run = chat_generator.run

            # This helper executes the actual LLM call and is decorated with @track
            @track(type="llm", name=f"llm-{llm_model}")
            def _execute_tracked_llm(
                messages, streaming_callback, generation_kwargs, tools, **kwargs
            ):
                try:
                    update_current_span(
                        metadata={
                            "model": llm_model,
                            "api_base_url": llm_url,
                            "generation_kwargs": generation_kwargs or {},
                        }
                    )
                except Exception:
                    pass
                return original_run(
                    messages,
                    streaming_callback=streaming_callback,
                    generation_kwargs=generation_kwargs,
                    tools=tools,
                    **kwargs,
                )

            # The actual method wrapper doesn't have the decorator directly, preventing signature issues.
            # functools.wraps preserves signature, making `inspect.signature` check in Agent constructor succeed.
            @functools.wraps(original_run)
            def opik_wrapped_run(
                messages,
                streaming_callback=None,
                generation_kwargs=None,
                tools=None,
                **kwargs,
            ):
                res = _execute_tracked_llm(
                    messages,
                    streaming_callback=streaming_callback,
                    generation_kwargs=generation_kwargs,
                    tools=tools,
                    **kwargs,
                )
                try:
                    if isinstance(res, dict) and "replies" in res:
                        for msg in res["replies"]:
                            meta = getattr(msg, "meta", None) or {}
                            usage = meta.get("usage", {}) or {}
                            if isinstance(usage, dict) and usage:
                                p_tok = usage.get("prompt_tokens", 0) or 0
                                c_tok = usage.get("completion_tokens", 0) or 0
                                details = (
                                    usage.get("completion_tokens_details", {}) or {}
                                )
                                r_tok = (
                                    details.get("reasoning_tokens", 0)
                                    or usage.get("reasoning_tokens", 0)
                                    or 0
                                )

                                from src.runtime.turn_compaction import _turn_runtime

                                if _turn_runtime is not None:
                                    rt = _turn_runtime.get()
                                    if isinstance(rt, dict):
                                        loop = rt.get("loop")
                                        queue = rt.get("queue")
                                        if loop and queue:
                                            loop.call_soon_threadsafe(
                                                queue.put_nowait,
                                                {
                                                    "type": "llm_tokens",
                                                    "prompt_tokens": p_tok,
                                                    "completion_tokens": c_tok,
                                                    "reasoning_tokens": r_tok,
                                                },
                                            )
                except Exception as tok_err:
                    logger.debug(
                        "Failed to extract token usage in opik_wrapped_run: %s", tok_err
                    )
                return res

            chat_generator.run = opik_wrapped_run

            # Wrap all tools to trace execution, using closure factory to prevent scope leaks
            wrapped_tools = []
            for tool in tools:
                original_fn = tool.function

                def make_wrapped_tool(orig_fn, name):
                    @track(type="tool", name=name)
                    @functools.wraps(orig_fn)
                    def opik_wrapped_tool_fn(*args, **kwargs):
                        return orig_fn(*args, **kwargs)

                    return opik_wrapped_tool_fn

                tool.function = make_wrapped_tool(original_fn, tool.name)
                wrapped_tools.append(tool)

            tools = wrapped_tools
            logger.info(
                "Opik telemetry wrappers successfully applied to chat_generator and tools with signature preservation."
            )
    except Exception as opik_err:
        logger.warning("Failed to apply Opik telemetry wrappers: %s", opik_err)

    # === LLM CALL TELEMETRY WRAPPERS ===
    try:
        import functools

        original_generator_run = chat_generator.run

        @functools.wraps(original_generator_run)
        def telemetry_wrapped_run(*args, **kwargs):
            from src.runtime.turn_compaction import _turn_runtime

            if _turn_runtime is not None:
                try:
                    rt = _turn_runtime.get()
                    if isinstance(rt, dict):
                        loop = rt.get("loop")
                        queue = rt.get("queue")
                        if loop and queue:
                            loop.call_soon_threadsafe(
                                queue.put_nowait, {"type": "llm_call"}
                            )
                except Exception:
                    pass
            return original_generator_run(*args, **kwargs)

        chat_generator.run = telemetry_wrapped_run

        if hasattr(chat_generator, "run_async"):
            original_generator_run_async = chat_generator.run_async

            @functools.wraps(original_generator_run_async)
            async def telemetry_wrapped_run_async(*args, **kwargs):
                from src.runtime.turn_compaction import _turn_runtime

                if _turn_runtime is not None:
                    try:
                        rt = _turn_runtime.get()
                        if isinstance(rt, dict):
                            loop = rt.get("loop")
                            queue = rt.get("queue")
                            if loop and queue:
                                loop.call_soon_threadsafe(
                                    queue.put_nowait, {"type": "llm_call"}
                                )
                    except Exception:
                        pass
                return await original_generator_run_async(*args, **kwargs)

            chat_generator.run_async = telemetry_wrapped_run_async
    except Exception as telemetry_err:
        logger.warning("Failed to apply LLM call telemetry wrappers: %s", telemetry_err)

    from src.runtime.model_tool_policy import filter_tools_for_model

    _policy_provider = "openai"
    _policy_model = llm_model
    if provider_loaded:
        _policy_provider = litellm_provider
        _policy_model = row.model_name
    elif "/" in (llm_model or ""):
        _policy_provider, _policy_model = (llm_model or "").split("/", 1)
    tools = filter_tools_for_model(
        tools, provider=_policy_provider, model_id=_policy_model
    )

    from src.runtime.tool_error_recovery import get_default_agent_hooks

    agent = create_aion_agent(
        chat_generator=chat_generator,
        tools=tools,
        system_prompt=system_prompt,
        max_agent_steps=min(
            int(os.getenv("AION_MAX_AGENT_STEPS", "15")),
            getattr(profile, "max_agent_steps", 999) or 999,
        ),
        hooks=get_default_agent_hooks(),
    )

    pair = (agent, profile.slug)
    logger.info(
        "agent_build_complete profile=%s session=%s tools_count=%d model=%s",
        profile.slug,
        session_id,
        len(tools),
        getattr(chat_generator, "model", llm_model),
    )
    if _AGENT_CACHE_ENABLED:
        async with _AGENT_CACHE_LOCK:
            _AGENT_CACHE[cache_key] = pair
            _AGENT_CACHE.move_to_end(cache_key)
            while len(_AGENT_CACHE) > _AGENT_CACHE_MAX:
                _AGENT_CACHE.popitem(last=False)
    if build_leader and build_waiter is not None and not build_waiter.done():
        build_waiter.set_result(pair)
    return pair
