from PIL.Image import logger
from typing import Optional
from src.observability.metrics import get_instance_id
import time
import datetime
from opentelemetry import trace
from src.runtime.hooks import hook_registry
from . import metrics

tracer = trace.get_tracer(__name__)

_tool_start_times = {}
_session_turn_tool_calls = {}  # session_id -> list of {tool_name, mcp_server, status}
_last_turn_tools_by_profile = {}  # profile -> list of tool summary dicts
_last_turn_tools_global = []
_last_turn_tokens_by_profile = {}
_last_turn_tokens_global = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "reasoning_tokens": 0,
    "total_tokens": 0,
}
_recent_mcp_errors = []  # rolling list of recent MCP tool call errors
_time_series_ring_buffer = []  # rolling list of {ts, tokens, turns, duration_sum, duration_count, tool_calls, profile, tenant_id}


def _record_ts_event(
    tokens=0, turns=0, duration=0.0, tool_calls=0, profile=None, tenant_id=None
):
    try:
        now = time.time()
        p = _resolve_profile(profile)
        t = tenant_id or "default"
        _time_series_ring_buffer.append(
            {
                "ts": now,
                "tokens": tokens,
                "turns": turns,
                "duration_sum": duration,
                "duration_count": 1 if duration > 0 else 0,
                "tool_calls": tool_calls,
                "profile": p,
                "tenant_id": t,
            }
        )
        # Keep rolling buffer under 2000 entries (~24h of high activity)
        if len(_time_series_ring_buffer) > 2000:
            _time_series_ring_buffer.pop(0)
    except Exception:
        pass


def get_last_turn_tools(profile: str = None):
    """Retrieve tool and MCP invocations from the most recent agent turn."""
    if profile:
        target = profile.strip().lower()
        for p, data in _last_turn_tools_by_profile.items():
            if p.strip().lower() == target:
                return data
    return _last_turn_tools_global


def get_all_last_turn_tools_by_profile() -> dict:
    """Retrieve last turn tools dictionary grouped by profile name."""
    return _last_turn_tools_by_profile


def get_last_turn_tokens(profile: str = None):
    """Retrieve LLM token breakdown (prompt, completion, reasoning) from the most recent agent turn."""
    if profile:
        target = profile.strip().lower()
        for p, data in _last_turn_tokens_by_profile.items():
            if p.strip().lower() == target:
                return data
    return _last_turn_tokens_global


def get_recent_mcp_errors(profile: str = None, limit: int = 50):
    """Retrieve recent MCP tool execution errors."""
    filtered = _recent_mcp_errors
    if profile:
        target = profile.strip().lower()
        filtered = [
            e
            for e in _recent_mcp_errors
            if e.get("profile", "").strip().lower() == target
        ]
    return filtered[:limit]


def _resolve_profile(ctx_profile: str = None) -> str:
    if ctx_profile and ctx_profile != "default":
        return ctx_profile
    try:
        from src.agent_pipeline import get_context

        c = get_context() or {}
        p_name = c.get("profile_name")
        if p_name:
            return p_name
    except Exception:
        pass
    return ctx_profile or "default"


def emit_tool_use_metric(
    session_id: str,
    server_name: str,
    tool_name: str,
    status: str,
    error_message: str = None,
    profile: str = None,
    tenant_id: str = None,
):
    """Emits tool call counter metrics by delegating to _on_post_tool_use."""
    try:
        from src.runtime.hooks import HookContext

        ctx = HookContext(
            event="post_tool_use",
            tenant_id=tenant_id or "default",
            conversation_id=session_id,
            user_id=tenant_id,
            profile=profile,
            payload={
                "tool_name": tool_name,
                "server_name": server_name,
                "status": status,
                "error": error_message,
            },
        )
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(_on_post_tool_use(ctx))
        except RuntimeError:
            import asyncio

            asyncio.run(_on_post_tool_use(ctx))
    except Exception as e:
        logger.debug(f"emit_tool_use_metric error: {e}")


async def _on_user_message(ctx):
    try:
        tenant_id = ctx.tenant_id or getattr(ctx, "user_id", None) or "default"
        profile = _resolve_profile(ctx.profile)
        inst_id = get_instance_id()
        metrics.aion_messages_total.labels(
            instance_id=inst_id,
            tenant_id=tenant_id,
            profile=profile,
            role="user",
            finish_reason="none",
        ).inc()
    except Exception:
        pass


async def _on_pre_tool_use(ctx):
    try:
        session_id = ctx.conversation_id
        tool_name = ctx.payload.get("tool_name")
        if session_id and tool_name:
            _tool_start_times[(session_id, tool_name)] = time.time()
    except Exception:
        pass


_recent_tool_dedupe_cache = {}


def resolve_mcp_server_dynamically(
    tool_name: str, mcp_server: Optional[str] = None
) -> str:
    """Risolve dinamicamente il server MCP di appartenenza di un tool."""
    if mcp_server and mcp_server not in ("unknown", "native", "local", None):
        return mcp_server

    if not tool_name:
        return "native"

    if "-" in tool_name:
        return tool_name.split("-", 1)[0]

    try:
        from src.mcp_manager import mcp_manager

        mcp_manager.load_registry()
        for srv_slug in mcp_manager._registry.keys():
            if srv_slug and (
                tool_name.startswith(f"{srv_slug}_")
                or tool_name.startswith(f"{srv_slug}-")
                or srv_slug.lower() in tool_name.lower()
            ):
                return srv_slug
    except Exception:
        pass

    if "_" in tool_name:
        prefix = tool_name.split("_", 1)[0]
        if prefix == "sandbox":
            return "session_sandbox"
        elif prefix in ("ocr", "skill"):
            return "skills_hub" if prefix == "skill" else prefix

    return "native"


async def _on_post_tool_use(ctx):
    try:
        raw_tool_name = (
            ctx.payload.get("tool_name") or ctx.payload.get("name") or "unknown"
        )
        status = ctx.payload.get("status") or (
            "error" if ctx.payload.get("error") else "ok"
        )
        tenant_id = ctx.tenant_id or getattr(ctx, "user_id", None) or "default"
        profile = _resolve_profile(ctx.profile)
        session_id = ctx.conversation_id or "default_session"
        mcp_server = ctx.payload.get("server_name") or ctx.payload.get("mcp_server")

        tool_name = raw_tool_name
        if "-" in tool_name and not mcp_server:
            parts = tool_name.split("-", 1)
            mcp_server = parts[0]
            tool_name = parts[1]

        mcp_server = resolve_mcp_server_dynamically(tool_name, mcp_server)

        now = time.time()
        dedupe_key = (session_id, mcp_server, tool_name, status)
        last_seen = _recent_tool_dedupe_cache.get(dedupe_key, 0)
        if now - last_seen < 0.5:
            # Skip duplicate hook dispatch within 500ms for exact same tool execution
            return
        _recent_tool_dedupe_cache[dedupe_key] = now

        inst_id = get_instance_id()
        metrics.aion_tool_calls_total.labels(
            instance_id=inst_id,
            tenant_id=tenant_id,
            profile=profile,
            tool_name=tool_name,
            mcp_server=mcp_server,
            status=status,
        ).inc()

        _record_ts_event(tool_calls=1, profile=profile, tenant_id=tenant_id)

        if status not in ("ok", "success"):
            err_raw = (
                ctx.payload.get("error")
                or ctx.payload.get("message")
                or ctx.payload.get("result")
                or "MCP tool execution error"
            )
            err_msg = str(err_raw)
            if err_msg.startswith("{"):
                try:
                    import json

                    err_json = json.loads(err_msg)
                    if isinstance(err_json, dict):
                        err_msg = (
                            err_json.get("message")
                            or err_json.get("error")
                            or err_json.get("detail")
                            or err_msg
                        )
                except Exception:
                    pass

            _recent_mcp_errors.insert(
                0,
                {
                    "timestamp": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                    "tool_name": tool_name,
                    "mcp_server": mcp_server,
                    "profile": profile,
                    "status": status,
                    "error_message": str(err_msg)[:500],
                },
            )
            if len(_recent_mcp_errors) > 100:
                _recent_mcp_errors.pop()

        if session_id:
            if session_id not in _session_turn_tool_calls:
                _session_turn_tool_calls[session_id] = []
            _session_turn_tool_calls[session_id].append(
                {
                    "tool_name": tool_name,
                    "mcp_server": mcp_server,
                    "status": status,
                }
            )

            if tool_name:
                start_time = _tool_start_times.pop((session_id, tool_name), None)
                if start_time:
                    duration = time.time() - start_time
                    metrics.aion_tool_call_duration_seconds.labels(
                        tool_name=tool_name, mcp_server=mcp_server
                    ).observe(duration)
    except Exception:
        pass


async def _on_post_turn(ctx):
    try:
        tenant_id = ctx.tenant_id or getattr(ctx, "user_id", None) or "default"
        profile = _resolve_profile(ctx.profile)
        session_id = ctx.conversation_id
        payload = ctx.payload or {}

        status = payload.get("status", "ok")
        duration = payload.get("duration", 0.0)
        model = payload.get("model", "unknown")

        # 1. Turn Duration (Histogram + Last Turn Gauge)
        inst_id = get_instance_id()
        metrics.aion_turn_duration_seconds.labels(
            instance_id=inst_id, tenant_id=tenant_id, profile=profile
        ).observe(duration)

        metrics.aion_last_turn_duration_seconds.labels(
            instance_id=inst_id, tenant_id=tenant_id, profile=profile
        ).set(duration)

        # Record tool calls for the last turn
        global _last_turn_tools_global, _last_turn_tokens_global
        raw_tools = _session_turn_tool_calls.pop(session_id, [])
        # Aggregate tool calls for last turn
        aggregated = {}
        for item in raw_tools:
            key = (item["tool_name"], item["mcp_server"], item["status"])
            aggregated[key] = aggregated.get(key, 0) + 1

        last_tools_list = [
            {
                "tool_name": k[0],
                "mcp_server": k[1],
                "status": k[2],
                "count": v,
            }
            for k, v in aggregated.items()
        ]
        _last_turn_tools_by_profile[profile] = last_tools_list
        _last_turn_tools_global = last_tools_list

        # 2. Messages Total (assistant response)
        metrics.aion_messages_total.labels(
            instance_id=inst_id,
            tenant_id=tenant_id,
            profile=profile,
            role="assistant",
            finish_reason="stop" if status == "ok" else status,
        ).inc()

        # 3. Token usage
        prompt_tokens = payload.get("prompt_tokens", 0)
        completion_tokens = payload.get("completion_tokens", 0)
        reasoning_tokens = payload.get("reasoning_tokens", 0)

        last_tokens_dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": prompt_tokens + completion_tokens + reasoning_tokens,
        }
        _last_turn_tokens_by_profile[profile] = last_tokens_dict
        _last_turn_tokens_global = last_tokens_dict

        _record_ts_event(
            tokens=prompt_tokens + completion_tokens + reasoning_tokens,
            turns=1,
            duration=duration,
            profile=profile,
            tenant_id=tenant_id,
        )

        # Set turn tokens gauge (always set to show the exact values of the last turn)
        metrics.aion_llm_turn_tokens.labels(
            instance_id=inst_id,
            tenant_id=tenant_id,
            profile=profile,
            model=model,
            token_type="prompt",
        ).set(prompt_tokens)

        metrics.aion_llm_turn_tokens.labels(
            instance_id=inst_id,
            tenant_id=tenant_id,
            profile=profile,
            model=model,
            token_type="completion",
        ).set(completion_tokens)

        metrics.aion_llm_turn_tokens.labels(
            instance_id=inst_id,
            tenant_id=tenant_id,
            profile=profile,
            model=model,
            token_type="reasoning",
        ).set(reasoning_tokens)

        # Increment cumulative totals
        if prompt_tokens > 0:
            metrics.aion_llm_tokens_total.labels(
                instance_id=inst_id,
                tenant_id=tenant_id,
                profile=profile,
                model=model,
                token_type="prompt",
            ).inc(prompt_tokens)

        if completion_tokens > 0:
            metrics.aion_llm_tokens_total.labels(
                instance_id=inst_id,
                tenant_id=tenant_id,
                profile=profile,
                model=model,
                token_type="completion",
            ).inc(completion_tokens)

        if reasoning_tokens > 0:
            metrics.aion_llm_tokens_total.labels(
                instance_id=inst_id,
                tenant_id=tenant_id,
                profile=profile,
                model=model,
                token_type="reasoning",
            ).inc(reasoning_tokens)
        # 4. LLM calls
        llm_calls = payload.get("llm_calls", 0)
        metrics.aion_llm_turn_calls.labels(
            instance_id=inst_id, tenant_id=tenant_id, profile=profile
        ).set(llm_calls)

        # 5. Agent failure tracking
        if status != "ok":
            err_type = payload.get("error_type") or "unknown"
            metrics.aion_agent_failures_total.labels(
                instance_id=inst_id,
                tenant_id=tenant_id,
                profile=profile,
                error_type=err_type,
            ).inc()

        # 6. Session cache size gauge
        if session_id:
            try:
                from src.session_workspace import session_root

                root_path = session_root(session_id)
                if root_path.exists():
                    total_size = sum(
                        p.stat().st_size for p in root_path.rglob("*") if p.is_file()
                    )
                    metrics.aion_session_cache_size_bytes.labels(
                        instance_id=inst_id, tenant_id=tenant_id
                    ).set(total_size)
            except Exception:
                pass

    except Exception:
        pass


def register_observability_hooks():
    """Register hooks for emitting traces and metrics."""
    hook_registry.register("on_user_message", _on_user_message, priority=90)
    hook_registry.register("pre_tool_use", _on_pre_tool_use, priority=90)
    hook_registry.register("pre_tool", _on_pre_tool_use, priority=90)
    hook_registry.register("post_tool_use", _on_post_tool_use, priority=90)
    hook_registry.register("post_tool", _on_post_tool_use, priority=90)
    hook_registry.register("post_turn", _on_post_turn, priority=90)
