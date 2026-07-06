from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger("aion.slash")

SlashHandler = Callable[["SlashContext"], Awaitable["SlashResult"]]


@dataclass
class SlashContext:
    raw: str
    conversation_id: str
    user_id: str
    profile_name: str
    tenant_id: str = "default"


@dataclass
class SlashResult:
    handled: bool
    message: Optional[str] = None
    sse_events: Optional[Sequence[Dict[str, Any]]] = None


class SlashCommandRouter:
    def __init__(self) -> None:
        self._routes: Dict[str, SlashHandler] = {}

    def list_commands(self) -> List[str]:
        return sorted(self._routes.keys())

    def register(self, name: str, handler: SlashHandler, description: str = "") -> None:
        self._routes[name.lstrip("/").lower()] = handler

    async def route(self, raw: str, ctx: SlashContext) -> SlashResult:
        s = (raw or "").strip()
        if not s.startswith("/"):
            return SlashResult(handled=False)
        cmd = s.split()[0].lower().lstrip("/")
        h = self._routes.get(cmd)
        if not h:
            return SlashResult(handled=False)
        return await h(ctx)


slash_router = SlashCommandRouter()


async def _slash_help(ctx: SlashContext) -> SlashResult:
    keys = sorted(slash_router.list_commands())
    return SlashResult(
        handled=True, message="Comandi: " + ", ".join(f"/{k}" for k in keys)
    )


slash_router.register("help", _slash_help, "help")


async def _slash_plan_removed(ctx: SlashContext) -> SlashResult:
    """Legacy /plan — no auto plan creation (use agent_mode=plan + model <plan> tag)."""
    _ = ctx
    return SlashResult(
        handled=True,
        message=(
            "The `/plan` slash command was removed.\n\n"
            "To create an execution plan: switch to **Plan** mode in the chat toolbar, "
            "describe your goal, and send — the model will emit `<plan>...</plan>` for the "
            "sidebar. Approve there, then continue in **Normal** mode for execution."
        ),
    )


async def _slash_clear(ctx: SlashContext) -> SlashResult:
    return SlashResult(
        handled=True,
        message="Command /clear: archive this conversation from the client and start a new one (UI integration in progress).",
    )


async def _slash_compact(ctx: SlashContext) -> SlashResult:
    from src.runtime.redis_client import redis_set_force_compact

    if ctx.conversation_id:
        await redis_set_force_compact(ctx.conversation_id)
    return SlashResult(
        handled=True,
        message=(
            "Context compaction scheduled for the next message in this chat "
            "(requires AION_CONTEXT_COMPRESS_ENABLED=1)."
        ),
    )


slash_router.register("plan", _slash_plan_removed, "removed — use Plan agent mode")
slash_router.register("clear", _slash_clear, "new conversation")
slash_router.register("compact", _slash_compact, "compress context")


async def _slash_ttc(ctx: SlashContext) -> SlashResult:
    from ..main import get_agent
    from ..agent_pipeline import AgentPipeline
    from ..ttc.engine import ttc_engine
    from ..ttc.strategies import TTCStrategyType

    task = ctx.raw.split(" ", 1)[1].strip() if " " in ctx.raw else ""
    if not task:
        return SlashResult(handled=True, message="Uso: /ttc <task>")

    try:
        agent_instance, p_name = await get_agent(
            ctx.profile_name, session_id=ctx.conversation_id, user_id=ctx.user_id
        )
        pipeline = AgentPipeline(
            agent_instance,
            session_id=ctx.conversation_id,
            profile_name=p_name,
            user_id=ctx.user_id,
        )

        strategy = ttc_engine.get_strategy(TTCStrategyType.REFINEMENT)
        res = await strategy.run(pipeline, task)

        final_msg = f"**TTC Strategy: Refinement (Attempts: {res.get('attempts', 1)})**\n\n{res.get('text', 'No output')}"
        return SlashResult(handled=True, message=final_msg)
    except Exception as e:
        return SlashResult(handled=True, message=f"TTC error: {e}")


slash_router.register("ttc", _slash_ttc, "Start task with Test-Time Compute")


async def _slash_present(ctx: SlashContext) -> SlashResult:
    topic = ctx.raw.split(" ", 1)[1].strip() if " " in ctx.raw else ""
    if topic:
        msg = (
            "Uso consigliato (skill-driven):\n"
            f"`Crea una presentazione su {topic}`\n\n"
            "L'agente scrivera' HTML da zero in `workspace/*.html` via tool sandbox e aprira' la preview in sidebar."
        )
    else:
        msg = (
            "Uso: `/present <topic>`\n\n"
            "Questo comando e' un helper: la generazione avviene nel normale flusso agente+skill+tool "
            "(HTML scritto da zero via `sandbox_write_workspace_file`), non direttamente dal router slash."
        )
    return SlashResult(handled=True, message=msg)


slash_router.register("present", _slash_present, "Crea presentazione HTML")
