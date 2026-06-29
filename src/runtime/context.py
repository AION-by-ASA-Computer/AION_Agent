import contextvars
import threading
from typing import Any, Dict, Optional

# ContextVar: propagato con contextvars.copy_context() nei worker del ToolInvoker Haystack
# (thread pool). threading.local() non copiava → web_search perdeva session_id/loop.
_forward_ctx: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "aion_agent_forward",
    default=None,
)


def set_context(
    session_id: str,
    loop: Any,
    queue: Any,
    stop_event: Any,
    *,
    turn_plan_id: Optional[str] = None,
) -> None:
    ctx: Dict[str, Any] = {
        "session_id": session_id,
        "loop": loop,
        "queue": queue,
        "stop_event": stop_event,
        # Shared mutable dict — same object in all tool threads for this turn.
        # Used by mark_task_completed to enforce one-call-per-turn semantics.
        "mark_once": {"used": False, "lock": threading.Lock()},
    }
    if turn_plan_id:
        ctx["turn_plan_id"] = turn_plan_id.strip()
    _forward_ctx.set(ctx)


def get_context() -> Dict[str, Any]:
    v = _forward_ctx.get()
    return v if isinstance(v, dict) else {}


def get_current_session_id() -> str:
    return get_context().get("session_id", "default")


def clear_context() -> None:
    _forward_ctx.set(None)
