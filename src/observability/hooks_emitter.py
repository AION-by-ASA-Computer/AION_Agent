import time
from opentelemetry import trace
from src.runtime.hooks import hook_registry
from . import metrics

tracer = trace.get_tracer(__name__)

# Temporary dictionary to store tool start times indexed by (session_id, tool_name)
_tool_start_times = {}


async def _on_user_message(ctx):
    try:
        tenant_id = ctx.tenant_id or "default"
        profile = ctx.profile or "default"
        metrics.aion_messages_total.labels(
            tenant_id=tenant_id, profile=profile, role="user", finish_reason="none"
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


async def _on_post_tool_use(ctx):
    try:
        tool_name = ctx.payload.get("tool_name", "unknown")
        status = ctx.payload.get("status", "ok")
        tenant_id = ctx.tenant_id or "default"
        profile = ctx.profile or "default"
        session_id = ctx.conversation_id
        mcp_server = ctx.payload.get("server_name") or "unknown"

        metrics.aion_tool_calls_total.labels(
            tenant_id=tenant_id,
            profile=profile,
            tool_name=tool_name,
            mcp_server=mcp_server,
            status=status,
        ).inc()

        if session_id and tool_name:
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
        tenant_id = ctx.tenant_id or "default"
        profile = ctx.profile or "default"
        session_id = ctx.conversation_id
        payload = ctx.payload or {}

        status = payload.get("status", "ok")
        duration = payload.get("duration", 0.0)
        model = payload.get("model", "unknown")

        # 1. Turn Duration
        metrics.aion_turn_duration_seconds.labels(
            tenant_id=tenant_id, profile=profile
        ).observe(duration)

        # 2. Messages Total (assistant response)
        metrics.aion_messages_total.labels(
            tenant_id=tenant_id,
            profile=profile,
            role="assistant",
            finish_reason="stop" if status == "ok" else status,
        ).inc()

        # 3. Token usage
        prompt_tokens = payload.get("prompt_tokens", 0)
        completion_tokens = payload.get("completion_tokens", 0)
        reasoning_tokens = payload.get("reasoning_tokens", 0)

        # Set turn tokens gauge (always set to show the exact values of the last turn)
        metrics.aion_llm_turn_tokens.labels(
            tenant_id=tenant_id, profile=profile, model=model, token_type="prompt"
        ).set(prompt_tokens)

        metrics.aion_llm_turn_tokens.labels(
            tenant_id=tenant_id, profile=profile, model=model, token_type="completion"
        ).set(completion_tokens)

        metrics.aion_llm_turn_tokens.labels(
            tenant_id=tenant_id, profile=profile, model=model, token_type="reasoning"
        ).set(reasoning_tokens)

        # Increment cumulative totals
        if prompt_tokens > 0:
            metrics.aion_llm_tokens_total.labels(
                tenant_id=tenant_id, profile=profile, model=model, token_type="prompt"
            ).inc(prompt_tokens)

        if completion_tokens > 0:
            metrics.aion_llm_tokens_total.labels(
                tenant_id=tenant_id,
                profile=profile,
                model=model,
                token_type="completion",
            ).inc(completion_tokens)

        if reasoning_tokens > 0:
            metrics.aion_llm_tokens_total.labels(
                tenant_id=tenant_id,
                profile=profile,
                model=model,
                token_type="reasoning",
            ).inc(reasoning_tokens)
        # 4. LLM calls
        llm_calls = payload.get("llm_calls", 0)
        metrics.aion_llm_turn_calls.labels(tenant_id=tenant_id, profile=profile).set(
            llm_calls
        )

        # 5. Agent failure tracking
        if status != "ok":
            err_type = payload.get("error_type") or "unknown"
            metrics.aion_agent_failures_total.labels(
                tenant_id=tenant_id, profile=profile, error_type=err_type
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
                        tenant_id=tenant_id
                    ).set(total_size)
            except Exception:
                pass

    except Exception:
        pass


def register_observability_hooks():
    """Register hooks for emitting traces and metrics."""
    hook_registry.register("on_user_message", _on_user_message, priority=90)
    hook_registry.register("pre_tool_use", _on_pre_tool_use, priority=90)
    hook_registry.register("post_tool_use", _on_post_tool_use, priority=90)
    hook_registry.register("post_turn", _on_post_turn, priority=90)
