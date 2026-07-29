"""Map Pi worker stream events to AION SSE queue chunks."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion.pi_turn_runner")

# Flush assistant token deltas to context_budget after this many estimated tokens.
_PI_ASSISTANT_BUDGET_FLUSH_TOKENS = 400
_PI_HISTORY_PREFIX_MAX_CHARS = int(
    os.getenv("AION_PI_HISTORY_PREFIX_MAX_CHARS", "12000") or "12000"
)


def _pi_history_role(msg: Any) -> str:
    role = getattr(msg, "role", None)
    if role is None and isinstance(msg, dict):
        role = msg.get("role")
    return str(role or "user")


def _count_pi_dialogue_messages(messages: List[Dict[str, Any]]) -> int:
    count = 0
    for msg in messages:
        role = str(msg.get("role") or "").strip().lower()
        if role in {"user", "assistant"}:
            count += 1
    return count


def format_pi_history_prefix(
    messages: Optional[List[Any]],
    *,
    max_chars: int = _PI_HISTORY_PREFIX_MAX_CHARS,
) -> str:
    """Format prior AION STM rows for a fresh Pi session (worker restart / cold start)."""
    from src.haystack_chat import chat_message_text

    rows = list(messages or [])
    if len(rows) <= 1:
        return ""
    lines: List[str] = []
    for msg in rows[:-1]:
        text = chat_message_text(msg).strip()
        if not text:
            continue
        lines.append(f"{_pi_history_role(msg)}: {text}")
    if not lines:
        return ""
    block = "\n\n".join(lines)
    if len(block) > max_chars:
        block = "…\n" + block[-max_chars:]
    return (
        "--- Previous messages in this chat (continue the same task) ---\n"
        f"{block}\n"
        "--- End previous messages ---\n\n"
    )


async def _resolve_pi_prompt_message(
    client: Any,
    session_id: str,
    *,
    user_message: str,
    preflight_messages: Optional[List[Any]],
    session_created: bool,
) -> str:
    """Hydrate Pi with AION STM when the worker session was just created empty."""
    if not session_created:
        return user_message
    try:
        existing = await client.get_messages(session_id)
    except Exception as exc:
        logger.debug("Pi get_messages before prompt skipped: %s", exc)
        existing = []
    if _count_pi_dialogue_messages(existing) > 0:
        return user_message
    prefix = format_pi_history_prefix(preflight_messages)
    if not prefix:
        return user_message
    logger.info(
        "pi_history_hydrate session=%s prior_msgs=%d prefix_chars=%d",
        session_id[:8],
        max(0, len(preflight_messages or []) - 1),
        len(prefix),
    )
    return prefix + user_message


async def _emit_pi_context_budget(
    session_id: str,
    queue: asyncio.Queue,
    *,
    phase: str,
) -> None:
    from src.runtime.turn_compaction import try_build_context_budget_event

    evt = try_build_context_budget_event(phase=phase, session_id=session_id)
    if evt:
        await queue.put(evt)


async def _flush_pi_context_budget(
    session_id: str,
    queue: asyncio.Queue,
    *,
    phase: str = "pi_turn_end",
) -> None:
    from src.runtime.turn_compaction import resolve_turn_runtime

    rt = resolve_turn_runtime(session_id)
    if isinstance(rt, dict):
        rt["pi_assistant_budget_pending"] = 0
    await _emit_pi_context_budget(session_id, queue, phase=phase)


async def _pi_track_stream_tokens(
    session_id: str,
    queue: asyncio.Queue,
    *,
    bucket: str,
    text: str,
    phase: str,
    flush: bool = False,
) -> None:
    from src.memory.context_compressor import count_tokens
    from src.runtime.turn_compaction import (
        record_pi_context_delta,
        resolve_turn_runtime,
    )

    piece = str(text or "")
    if not piece:
        return
    delta = count_tokens(piece)
    if delta <= 0:
        return
    record_pi_context_delta(session_id, bucket, delta)
    rt = resolve_turn_runtime(session_id)
    if not isinstance(rt, dict):
        return
    if bucket == "assistant" and not flush:
        pending = int(rt.get("pi_assistant_budget_pending") or 0) + delta
        if pending < _PI_ASSISTANT_BUDGET_FLUSH_TOKENS:
            rt["pi_assistant_budget_pending"] = pending
            return
        rt["pi_assistant_budget_pending"] = 0
    await _emit_pi_context_budget(session_id, queue, phase=phase)


def pi_thinking_level_for_effort(reasoning_effort: Optional[str]) -> str:
    """Map AION reasoning_effort (min|medium|max) to Pi ThinkingLevel."""
    from src.runtime.reasoning_effort import normalize_reasoning_effort

    effort = normalize_reasoning_effort(reasoning_effort)
    if effort == "min":
        return "off"
    if effort == "max":
        return "high"
    return "medium"


async def _abort_stale_pi_session(client: Any, session_id: str) -> None:
    """Kill orphaned Pi worker turns (client disconnected but worker still prompting)."""
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        await client.abort_session(sid)
        logger.info("pi_abort_stale session=%s", sid[:8])
    except Exception as exc:
        logger.debug("pi_abort_stale skipped session=%s: %s", sid[:8], exc)


async def run_pi_agent_turn(
    *,
    session_id: str,
    profile_name: str,
    user_id: str,
    user_message: str,
    queue: asyncio.Queue,
    stop_event: Any,
    loop: asyncio.AbstractEventLoop,
    llm_provider_name: Optional[str] = None,
    agent_tools: Optional[list] = None,
    reasoning_effort: Optional[str] = None,
    preflight_messages: Optional[List[Any]] = None,
) -> None:
    """Execute one long-run turn via Pi worker; push chunks to ``queue``."""
    from src.agent_profile import profile_manager
    from src.runtime.context import clear_context, set_context
    from src.runtime.pi_runtime.pi_client import PiWorkerClient, pi_worker_healthy
    from src.runtime.pi_runtime.session_config import prepare_pi_session_files
    from src.runtime.pi_runtime.tool_manifest import (
        build_tool_manifest,
        clear_session_tool_registry,
        tools_to_pi_manifest,
        write_tool_manifest,
    )
    from src.session_workspace import session_root

    if not await pi_worker_healthy():
        await queue.put(
            {
                "type": "error",
                "content": (
                    "Long Run mode requires the Pi worker. "
                    "Start it with: cd services/pi-long-run && pnpm dev"
                ),
            }
        )
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})
        return

    profile = profile_manager.get_profile(profile_name)
    workspace = str(session_root(session_id) / "workspace")
    clear_session_tool_registry(session_id)
    set_context(session_id, loop, queue, stop_event)
    client = PiWorkerClient()
    await _abort_stale_pi_session(client, session_id)
    stream_chunks = 0
    try:
        agent_dir, llm_cfg = await prepare_pi_session_files(
            session_id,
            profile,
            llm_provider_name=llm_provider_name,
        )
        if agent_tools:
            manifest = tools_to_pi_manifest(session_id, agent_tools)
            logger.info(
                "pi_tool_manifest session=%s tools=%d (reused agent cache)",
                session_id[:8],
                len(manifest),
            )
        else:
            logger.info(
                "pi_tool_manifest session=%s discovering tools...", session_id[:8]
            )
            manifest = await build_tool_manifest(session_id, profile, user_id)
            logger.info(
                "pi_tool_manifest session=%s tools=%d (fresh discovery)",
                session_id[:8],
                len(manifest),
            )
        manifest_path = write_tool_manifest(session_id, manifest)

        from src.mcp_manager import mcp_manager

        try:
            await mcp_manager.warm_session(
                session_id,
                profile.mcp_servers or [],
                profile_slug=profile_name,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning("pi warm_session failed session=%s: %s", session_id[:8], exc)

        from src.runtime.long_run_mode import pi_worker_secret

        model_id = llm_cfg.model_id

        logger.info(
            "pi_ensure_session session=%s model=%s worker=%s",
            session_id[:8],
            model_id,
            client.base_url,
        )
        thinking_level = pi_thinking_level_for_effort(reasoning_effort)
        from src.runtime.llm_limits import (
            pi_runtime_config_fingerprint,
            resolve_chat_max_tokens,
        )
        from src.runtime.pi_runtime.pi_compaction import pi_custom_compaction_enabled
        from src.runtime.tool_ledger import tool_ledger_enabled

        max_tokens = resolve_chat_max_tokens(long_run=True)
        api_base = (os.getenv("AION_PUBLIC_API_URL") or "http://127.0.0.1:8001").rstrip(
            "/"
        )
        ensured = await client.ensure_session(
            {
                "session_id": session_id,
                "workspace_dir": workspace,
                "agent_dir": str(agent_dir),
                "model_id": model_id,
                "provider_id": "aion",
                "thinking_level": thinking_level,
                "tool_manifest_path": str(manifest_path),
                "invoke_url": f"{api_base}/internal/pi/tools/invoke",
                "invoke_secret": pi_worker_secret(),
                "profile": profile_name,
                "user_id": user_id,
                "api_base_url": api_base,
                "ledger_enabled": tool_ledger_enabled(),
                "custom_compaction_enabled": pi_custom_compaction_enabled(),
                "config_fingerprint": pi_runtime_config_fingerprint(),
                "max_tokens": max_tokens,
            }
        )
        session_created = bool(ensured.get("created"))
        pi_prompt = await _resolve_pi_prompt_message(
            client,
            session_id,
            user_message=user_message,
            preflight_messages=preflight_messages,
            session_created=session_created,
        )
        logger.info(
            "pi_stream_prompt session=%s chars=%d hydrated=%s",
            session_id[:8],
            len(pi_prompt),
            pi_prompt != user_message,
        )

        async for chunk in client.stream_prompt(
            session_id,
            pi_prompt,
            stop_event=stop_event,
        ):
            if stop_event.is_set():
                break
            stream_chunks += 1
            ctype = str(chunk.get("type") or "")
            if ctype == "done":
                continue
            if ctype == "context_compacting_start":
                await queue.put({"type": "context_compacting", "active": True})
                continue
            if ctype == "context_compacting_end":
                await queue.put({"type": "context_compacting", "active": False})
                continue
            if ctype == "reasoning":
                await _pi_track_stream_tokens(
                    session_id,
                    queue,
                    bucket="reasoning",
                    text=str(chunk.get("reasoning") or ""),
                    phase="pi_reasoning",
                    flush=True,
                )
            elif ctype == "token":
                await _pi_track_stream_tokens(
                    session_id,
                    queue,
                    bucket="assistant",
                    text=str(chunk.get("content") or ""),
                    phase="pi_token",
                )
            await queue.put(chunk)

    except Exception as exc:
        logger.error(
            "Pi turn failed session=%s: %s", session_id[:8], exc, exc_info=True
        )
        await queue.put({"type": "error", "content": str(exc)})
    finally:
        if stream_chunks == 0 and not stop_event.is_set():
            logger.warning(
                "pi_stream_empty session=%s (worker returned no NDJSON chunks; "
                "check for orphaned prompt or Pi worker logs)",
                session_id[:8],
            )
        clear_context()
        try:
            from src.runtime.tool_circuit import reset_session_circuit

            reset_session_circuit(session_id)
        except Exception:
            pass
        await _flush_pi_context_budget(session_id, queue)
        loop.call_soon_threadsafe(queue.put_nowait, {"type": "done"})


async def sync_pi_messages_to_history(
    session_id: str,
    profile_name: str,
    user_id: str,
    assistant_message_id: Optional[str],
    history_manager: Any,
) -> None:
    """Post-turn: persist assistant text from Pi if stream flush missed it."""
    if not assistant_message_id:
        return
    from src.runtime.pi_runtime.pi_client import PiWorkerClient

    client = PiWorkerClient()
    try:
        messages = await client.get_messages(session_id)
    except Exception as exc:
        logger.debug("Pi get_messages failed: %s", exc)
        return

    assistant_text = ""
    for msg in reversed(messages):
        role = str(msg.get("role") or "")
        if role == "assistant":
            content = msg.get("content")
            if isinstance(content, str):
                assistant_text = content
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text") or ""))
                assistant_text = "".join(parts)
            break

    if not assistant_text.strip():
        return

    try:
        await history_manager.upsert_message_content(
            session_id,
            assistant_message_id,
            "assistant",
            assistant_text,
            profile_name=profile_name,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("Pi history sync failed: %s", exc)
