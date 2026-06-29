"""StreamLoop: the main `while True` queue consumption loop extracted from AgentPipeline.run_stream.

Activate via ``AION_STREAM_LOOP_V2=1``.  When the flag is off the existing
inline loop in agent_pipeline.py runs unchanged (safe rollback path).

Design principles
-----------------
* All mutable state is held as instance attributes so the caller can inspect
  ``full_response``, ``stop_reason``, etc. after the generator exhausts.
* No hidden globals: every dependency is injected via the constructor.
* ``StreamLoop.consume()`` is an async generator that yields SSE event dicts.
  Callers wrap each yield with ``_track_sse(event)`` as needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
)

if TYPE_CHECKING:
    from src.runtime.artifact_manager import ArtifactManager
    from src.runtime.artifact_parser import (
        ArtifactEvent,
        XMLArtifactStreamParser,
    )
    from src.runtime.plan_engine import PlanModeController
    from src.runtime.stream.demux import StreamDemux
    from src.runtime.turn.turn_guards import TurnGuards
    from src.runtime.turn.turn_persistence import TurnPersistence
    from src.runtime.stream_sync import StreamSync

logger = logging.getLogger("aion.stream_loop")


class StreamLoop:
    """Encapsulates the main streaming event consumption loop.

    Parameters
    ----------
    queue:
        Asyncio queue fed by the agent thread and the tool-event listener.
    stop_event:
        Threading event used to request early agent termination.
    loop:
        The running event loop (needed for ``loop.time()``).
    turn_guards:
        Pre-configured budget guards.
    artifact_parser:
        Stateful artifact stream parser for this turn.
    artifact_manager:
        Manages saving artifact blobs to disk.
    turn_persist:
        Handles DB persistence of tool steps and messages.
    session_id, profile_name, user_id:
        Identity fields forwarded to persistence / hooks.
    assistant_message_id:
        Pre-allocated assistant message ID.
    plan_controller:
        Optional ``PlanModeController`` for plan-mode turns.
    message_source:
        Raw ``message_source`` string (``'user_input'``, ``'internal_trigger'``, …).
    plan_text_parser_enabled_fn:
        Callable returning whether plan-text-parser mode is active.
    demux:
        Optional ``StreamDemux`` instance for plan/artifact side channels.
    track_sse:
        Optional callable applied to every yielded event
        (e.g. ``timeline_builder.apply_chunk``).  Receives the event dict and
        must return it (or a mutated copy).
    """

    def __init__(
        self,
        *,
        queue: asyncio.Queue,
        stop_event: "Any",  # threading.Event
        loop: asyncio.AbstractEventLoop,
        turn_guards: "TurnGuards",
        artifact_parser: Any,
        artifact_manager: "ArtifactManager",
        turn_persist: "TurnPersistence",
        session_id: str,
        profile_name: str,
        user_id: str,
        assistant_message_id: Optional[str],
        plan_controller: Optional["PlanModeController"] = None,
        message_source: str = "user_input",
        plan_text_parser_enabled_fn: Optional[Callable[[], bool]] = None,
        demux: Optional["StreamDemux"] = None,
        track_sse: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.queue = queue
        self.stop_event = stop_event
        self.loop = loop
        self.turn_guards = turn_guards
        self.artifact_parser = artifact_parser
        self.artifact_manager = artifact_manager
        self.turn_persist = turn_persist
        self.session_id = session_id
        self.profile_name = profile_name
        self.user_id = user_id
        self.assistant_message_id = assistant_message_id
        self.plan_controller = plan_controller
        self._msg_src = (message_source or "user_input").strip()
        self._plan_text_parser_enabled = plan_text_parser_enabled_fn or (lambda: False)
        self._demux = demux
        self._track_sse = track_sse or (lambda x: x)

        # Budget limits (unpacked for fast inner-loop access)
        g = turn_guards
        self.max_reasoning_chars = g.max_reasoning_chars
        self.max_reasoning_events = g.max_reasoning_events
        self.max_tool_events = g.max_tool_events
        self.max_tool_calls = g.max_tool_calls
        self.max_stream_events = g.max_stream_events
        self.max_control_events = g.max_control_events
        self.max_output_events = g.max_output_events
        self.max_output_chars = g.max_output_chars
        self.no_progress_timeout = g.no_progress_timeout
        self.min_reasoning_chars_without_tool = g.min_reasoning_chars_without_tool
        self.max_reasoning_events_without_tool = g.max_reasoning_events_without_tool
        self.reasoning_hard_stop = g.reasoning_hard_stop

        _single = os.getenv("AION_ORCH_EVENT_SINGLE_CHANNEL", "1").strip().lower()
        self.single_orch_channel = _single in ("1", "true", "yes", "on")

        # Mutable state (accessible post-consume)
        self.full_response: List[str] = []
        self.full_reasoning: List[str] = []
        self.tool_calls_log: List[Dict[str, Any]] = []
        self.stop_reason: str = "completed"
        self.pending_write_artifacts: Dict[str, Dict[str, Any]] = {}
        self.artifact_parse_hits: int = 0
        self.artifact_salvage: int = 0
        self.plan_intercepts: int = 0
        self.plan_finalize_source: Optional[str] = None
        self.plan_text_fallback_count: int = 0
        self.raw_token_fallback_chunks: int = 0

        # Inner counters mirroring turn_guards.state
        self.is_streaming: bool = False
        self.reasoning_chars: int = 0
        self.reasoning_events: int = 0
        self.tool_events: int = 0
        self.tool_calls: int = 0
        self.stream_events: int = 0
        self.control_events: int = 0
        self.output_events: int = 0
        self.output_chars: int = 0
        self.last_progress_at: float = g.state.last_progress_at
        self.reasoning_guard_logged: bool = g.state.reasoning_guard_logged
        self.reasoning_no_tool_warned: bool = g.state.reasoning_no_tool_warned

    # ------------------------------------------------------------------
    # Public: main async generator
    # ------------------------------------------------------------------

    async def consume(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Run the main `while True` event consumption loop.

        Yields SSE event dicts (already run through ``track_sse`` if provided).
        The generator exits when a ``done`` or hard-stop condition is reached.
        """
        from src.agent_pipeline import _chunk_counters, _agent_debug_log
        from src.runtime.artifact_parser import ArtifactEvent
        from src.runtime.stream_sync import StreamSync

        async with asyncio.timeout(self.turn_guards.turn_timeout):
            while True:
                if self.queue.empty() and not self.is_streaming:
                    StreamSync.mark_caught_up(self.session_id)

                chunk = await self.queue.get()
                self.stream_events += 1
                ctype = str(chunk.get("type") or "")
                evt_for_counter = chunk.get("event") or {}
                c_inc, o_inc = _chunk_counters(
                    ctype, str(evt_for_counter.get("type") or "")
                )
                self.control_events += c_inc
                self.output_events += o_inc
                if ctype in ("token", "artifact_content"):
                    self.output_chars += len(str(chunk.get("content") or ""))
                if ctype == "reasoning":
                    self.output_chars += len(str(chunk.get("reasoning") or ""))

                # Route through demux side channels
                if self._demux is not None:
                    self._demux.feed(chunk)

                # --- Hard-stop budget guards ---
                hard_stop = self._check_budget_guards(ctype)
                if hard_stop is not None:
                    yield self._track_sse(hard_stop)
                    break

                # --- Keepalive ---
                if ctype == "keepalive":
                    self.last_progress_at = self.loop.time()
                    continue

                # --- Done signal ---
                if ctype == "done":
                    _agent_debug_log(
                        "H4",
                        "stream_loop:done",
                        "queue_done_received",
                        {
                            "session_id": self.session_id[:12],
                            "full_response_len": len("".join(self.full_response)),
                            "stop_reason": self.stop_reason,
                            "tool_calls": self.tool_calls,
                        },
                    )
                    break

                # --- Error / context_length_error ---
                if ctype in ("error", "context_length_error"):
                    _agent_debug_log(
                        "H1",
                        "stream_loop:queue_error",
                        "queue_error_chunk",
                        {
                            "session_id": self.session_id[:12],
                            "content": str(chunk.get("content") or "")[:300],
                        },
                    )
                    yield self._track_sse(chunk)
                    break

                # --- Token events ---
                if ctype == "token":
                    async for evt in self._handle_token(chunk):
                        yield evt
                    continue

                # --- Reasoning events ---
                if ctype == "reasoning":
                    async for evt in self._handle_reasoning(chunk):
                        yield evt
                    continue

                # --- Stream end ---
                if ctype == "stream_end":
                    self.is_streaming = False
                    continue

                # --- Tool events ---
                if ctype == "tool_event":
                    should_break = False
                    async for evt in self._handle_tool_event(chunk):
                        if isinstance(evt, _BreakSignal):
                            should_break = True
                        else:
                            yield evt
                    if should_break:
                        break

    # ------------------------------------------------------------------
    # Private: token handler
    # ------------------------------------------------------------------

    async def _handle_token(
        self, chunk: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from src.agent_pipeline import (
            _is_plan_artifact_payload,
            _plan_artifact_sse_end,
            _resolve_turn_plan_id,
            _setup_plan_artifact_chunk,
        )
        from src.runtime.artifact_parser import ArtifactEvent

        self.is_streaming = True
        had_only_text = True
        raw_token = chunk.get("content") or ""
        text_emitted = False

        for pe in self.artifact_parser.feed(raw_token):
            if pe.event == ArtifactEvent.TEXT:
                if pe.content:
                    self.full_response.append(pe.content)
                    text_emitted = True
                self.last_progress_at = self.loop.time()
                yield self._track_sse({"type": "token", "content": pe.content})
                await self.turn_persist.flush_assistant_stream_content(
                    full_response=self.full_response,
                    full_reasoning=self.full_reasoning,
                    profile_name=self.profile_name,
                    user_id=self.user_id,
                    loop_time=self.loop.time(),
                )
            elif pe.event == ArtifactEvent.ARTIFACT_START:
                had_only_text = False
                self.artifact_parse_hits += 1
                if (pe.artifact_type or "").strip().lower() == "plan":
                    self.plan_intercepts += 1
                yield self._track_sse(
                    {
                        "type": "artifact_start",
                        "artifact": {
                            "identifier": pe.artifact_id,
                            "type": pe.artifact_type,
                            "title": pe.artifact_title,
                            "auto_execute": pe.auto_execute,
                        },
                    }
                )
            elif pe.event == ArtifactEvent.ARTIFACT_CONTENT:
                had_only_text = False
                if pe.content:
                    self.last_progress_at = self.loop.time()
                yield self._track_sse(
                    {
                        "type": "artifact_content",
                        "content": pe.content,
                        "artifact_id": pe.artifact_id,
                    }
                )
            elif pe.event == ArtifactEvent.ARTIFACT_END:
                had_only_text = False
                async for evt in self._finalize_artifact(pe):
                    yield evt

        if self.plan_controller:
            _prog = self.plan_controller.maybe_progress_sse("".join(self.full_response))
            if _prog:
                yield self._track_sse(_prog)

        if (
            had_only_text
            and not text_emitted
            and raw_token
            and not getattr(
                self.artifact_parser, "is_suppressing_tokens", lambda: False
            )()
        ):
            _suppress_plan_token = False
            if self.plan_controller is not None and self._plan_text_parser_enabled():
                from src.runtime.plan_engine import should_suppress_plan_token

                _suppress_plan_token = should_suppress_plan_token(
                    raw_token, "".join(self.full_response)
                )
            self.full_response.append(raw_token)
            self.raw_token_fallback_chunks += 1
            if not _suppress_plan_token:
                self.last_progress_at = self.loop.time()
                yield self._track_sse({"type": "token", "content": raw_token})
                await self.turn_persist.flush_assistant_stream_content(
                    full_response=self.full_response,
                    full_reasoning=self.full_reasoning,
                    profile_name=self.profile_name,
                    user_id=self.user_id,
                    loop_time=self.loop.time(),
                )
        elif had_only_text:
            self.raw_token_fallback_chunks += 1

    # ------------------------------------------------------------------
    # Private: reasoning handler
    # ------------------------------------------------------------------

    async def _handle_reasoning(
        self, chunk: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from src.agent_pipeline import _agent_debug_log

        self.is_streaming = True
        reasoning_piece = chunk.get("reasoning") or ""
        if reasoning_piece:
            self.last_progress_at = self.loop.time()
        self.reasoning_events += 1
        self.reasoning_chars += len(reasoning_piece)

        over_events = (
            self.max_reasoning_events > 0
            and self.reasoning_events > self.max_reasoning_events
        )
        over_chars = (
            self.max_reasoning_chars > 0
            and self.reasoning_chars > self.max_reasoning_chars
        )

        if not self.reasoning_guard_logged and (over_events or over_chars):
            self.reasoning_guard_logged = True
            _agent_debug_log(
                "H1",
                "stream_loop:reasoning_guard",
                "reasoning_threshold_crossed",
                {
                    "session_id": self.session_id[:12],
                    "over_events": over_events,
                    "over_chars": over_chars,
                    "reasoning_events": self.reasoning_events,
                    "max_reasoning_events": self.max_reasoning_events,
                    "reasoning_chars": self.reasoning_chars,
                    "max_reasoning_chars": self.max_reasoning_chars,
                },
            )

        if self.reasoning_hard_stop and (over_events or over_chars):
            self.stop_event.set()
            self.stop_reason = "reasoning_budget"
            msg = (
                "Interrotto automaticamente: reasoning loop oltre soglia "
                f"(events={self.reasoning_events}/{self.max_reasoning_events}, "
                f"chars={self.reasoning_chars}/{self.max_reasoning_chars})."
            )
            logger.warning("Hard-stop reasoning guard: %s", msg)
            yield self._track_sse({"type": "error", "content": msg})
            # Caller checks stop_reason to break
            return

        _chars_gate = (
            self.min_reasoning_chars_without_tool > 0
            and self.reasoning_chars >= self.min_reasoning_chars_without_tool
        )
        _events_gate = (
            self.max_reasoning_events_without_tool > 0
            and self.reasoning_events >= self.max_reasoning_events_without_tool
        )
        _no_tool_warn = (
            self.tool_calls == 0
            and not self.reasoning_no_tool_warned
            and (
                _chars_gate
                or (
                    self.max_reasoning_events_without_tool > 0
                    and _events_gate
                    and self.min_reasoning_chars_without_tool <= 0
                )
            )
        )
        if _no_tool_warn:
            self.reasoning_no_tool_warned = True
            logger.warning(
                "reasoning without tool: chars=%s events=%s tool_calls=0 session=%s",
                self.reasoning_chars,
                self.reasoning_events,
                self.session_id[:12],
            )
            yield self._track_sse(
                {
                    "type": "turn_status",
                    "phase": "reasoning_guard",
                    "message": (
                        "Molto reasoning senza tool: esegui la query o un tool "
                        "rilevante (SQL, memoria, OpenMetadata, …) oppure rispondi."
                    ),
                }
            )

        self.full_reasoning.append(reasoning_piece)
        yield self._track_sse(chunk)
        await self.turn_persist.flush_assistant_stream_content(
            full_response=self.full_response,
            full_reasoning=self.full_reasoning,
            profile_name=self.profile_name,
            user_id=self.user_id,
            loop_time=self.loop.time(),
        )

    # ------------------------------------------------------------------
    # Private: tool_event handler
    # ------------------------------------------------------------------

    async def _handle_tool_event(
        self, chunk: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Handle a ``tool_event`` chunk.

        Yields regular event dicts or a ``_BreakSignal`` sentinel when the
        caller should break out of the loop.
        """
        from src.agent_pipeline import (
            _agent_debug_log,
            _is_plan_artifact_payload,
            _plan_artifact_sse_end,
            _resolve_turn_plan_id,
            _setup_plan_artifact_chunk,
        )
        from src.runtime.artifact_parser import ArtifactEvent
        from src.runtime.stream_sync import StreamSync
        from src.memory.context_compressor import count_tokens

        self.tool_events += 1
        self.last_progress_at = self.loop.time()

        if self.max_tool_events > 0 and self.tool_events > self.max_tool_events:
            self.stop_event.set()
            self.stop_reason = "tool_events_limit"
            msg = (
                "Interrotto automaticamente: troppi eventi tool nel turno "
                f"({self.tool_events}/{self.max_tool_events})."
            )
            logger.warning("Hard-stop tool-event guard: %s", msg)
            yield {"type": "error", "content": msg}
            yield _BreakSignal()
            return

        evt = chunk.get("event") or {}

        # --- tool_start ---
        if evt.get("type") == "tool_start":
            self.tool_calls += 1
            _tn = str(evt.get("name") or "")

            # internal_trigger: mark_once guard
            if self._msg_src == "internal_trigger" and _tn != "mark_task_completed":
                try:
                    from src.runtime.context import get_context

                    _mo = get_context().get("mark_once")
                    if isinstance(_mo, dict) and _mo.get("used"):
                        self.stop_event.set()
                        self.stop_reason = "plan_mark_already_used"
                        _block_msg = (
                            "mark_task_completed was already called this turn. "
                            "STOP — do not call more tools."
                        )
                        yield self._track_sse({"type": "error", "content": _block_msg})
                        yield _BreakSignal()
                        return
                except Exception:
                    pass

            # plan_controller research budget
            if self.plan_controller is not None:
                _allowed, _budget_msg = self.plan_controller.on_research_tool_start(_tn)
                if not _allowed:
                    yield self._track_sse(
                        self.plan_controller.sse_phase(
                            "research_budget_reached", message=_budget_msg
                        )
                    )
                    yield self._track_sse(
                        {
                            "type": "turn_status",
                            "phase": "plan_research_budget",
                            "tool": _tn,
                            "message": _budget_msg or "",
                        }
                    )
                    self.stop_event.set()
                    self.stop_reason = "plan_research_budget"
                    yield self._track_sse(
                        {"type": "error", "content": _budget_msg or ""}
                    )
                    yield _BreakSignal()
                    return

            # MemPalace status notification
            if _tn.startswith("mempalace_"):
                yield self._track_sse(
                    {
                        "type": "turn_status",
                        "phase": "mempalace",
                        "tool": _tn,
                        "message": (
                            f"MemPalace · {_tn} "
                            f"({self.tool_calls}/{self.max_tool_calls or '∞'})"
                        ),
                    }
                )

            if self.tool_calls in (1, 3, 5, 8, 12, 16, 20):
                _agent_debug_log(
                    "H3",
                    "stream_loop:tool_start",
                    "tool_call_milestone",
                    {
                        "session_id": self.session_id[:12],
                        "tool_calls": self.tool_calls,
                        "tool_name": str(evt.get("name") or "")[:64],
                        "reasoning_chars_so_far": self.reasoning_chars,
                        "output_chars_so_far": self.output_chars,
                    },
                )

            if self.max_tool_calls > 0 and self.tool_calls > self.max_tool_calls:
                self.stop_event.set()
                self.stop_reason = "tool_calls_limit"
                msg = (
                    "Interrotto automaticamente: troppi tool call nel turno "
                    f"({self.tool_calls}/{self.max_tool_calls})."
                )
                logger.warning("Hard-stop tool-call guard: %s", msg)
                yield {"type": "error", "content": msg}
                yield _BreakSignal()
                return

            # Track pending write artifacts
            if evt.get("name") == "sandbox_write_workspace_file":
                args = evt.get("input", {}) or {}
                rp = str(args.get("relative_path") or "workspace/file.txt")
                ct = str(args.get("content") or "")
                self.pending_write_artifacts[rp] = {"content": ct, "mode": "write"}
            elif evt.get("name") == "sandbox_edit_workspace_file":
                args = evt.get("input", {}) or {}
                rp = str(args.get("relative_path") or "workspace/file.txt")
                self.pending_write_artifacts[rp] = {
                    "old_string": str(args.get("old_string") or ""),
                    "new_string": str(args.get("new_string") or ""),
                    "mode": "edit",
                }

        # --- request_sync ---
        if evt.get("type") == "request_sync":
            self.is_streaming = False
            for pe in self.artifact_parser.flush():
                if pe.event == ArtifactEvent.ARTIFACT_END:
                    async for artifact_evt in self._finalize_artifact(pe):
                        yield artifact_evt
            StreamSync.mark_caught_up(self.session_id)
            return  # continue (not break)

        self.tool_calls_log.append(evt)

        # --- tool_end / tool_error: exploration + QM hooks ---
        if evt.get("type") in ("tool_end", "tool_error"):
            try:
                import src.runtime.db_navigation_mempalace_hooks  # noqa: F401
                import src.runtime.exploration_tracker  # noqa: F401
                from src.runtime.exploration_tracker import record_exploration_tool
                from src.runtime.datasource_memory_mode import (
                    maybe_append_same_turn_reminder,
                )

                _tool_out = evt.get("output") or evt.get("error")
                record_exploration_tool(
                    session_id=self.session_id,
                    tool_name=str(evt.get("name") or ""),
                    event_type=str(evt.get("type") or ""),
                    output=_tool_out,
                    profile_slug=self.profile_name,
                )
                if evt.get("type") == "tool_end":
                    _tool_out = maybe_append_same_turn_reminder(
                        session_id=self.session_id,
                        profile_slug=self.profile_name,
                        tool_name=str(evt.get("name") or ""),
                        event_type="tool_end",
                        output=_tool_out,
                    )
                    evt["output"] = _tool_out
                _tenant_qm = (
                    os.getenv("AION_DEFAULT_TENANT_ID") or "default"
                ).strip() or "default"
                from src.runtime.hooks import HookContext, hook_registry

                await hook_registry.dispatch(
                    "post_tool",
                    HookContext(
                        event="post_tool",
                        tenant_id=_tenant_qm,
                        conversation_id=self.session_id,
                        user_id=self.user_id,
                        profile=self.profile_name,
                        payload={
                            "event_type": evt.get("type"),
                            "tool_name": evt.get("name"),
                            "tool_input": evt.get("input"),
                            "output": evt.get("output") or evt.get("error"),
                        },
                    ),
                )
            except Exception as qm_post_exc:
                logger.debug("sql_qm post_tool: %s", qm_post_exc)

        # --- orchestration events ---
        et = evt.get("type")
        if isinstance(et, str) and et.startswith("orchestration_"):
            yield {k: v for k, v in evt.items()}
            if et == "orchestration_plan_pending":
                self.plan_intercepts += 1
                if self.plan_controller is not None:
                    yield self._track_sse(self.plan_controller.sse_phase("registered"))
            if self.single_orch_channel:
                return  # continue

        # --- sandbox_write_workspace_file tool_end ---
        if (
            evt.get("type") == "tool_end"
            and evt.get("name") == "sandbox_write_workspace_file"
        ):
            output_text = str(evt.get("output") or "")
            saved_path = ""
            if "workspace/" in output_text:
                saved_path = output_text.split("workspace/", 1)[1].strip()
                saved_path = "workspace/" + saved_path.split()[0].strip("`\"'.,)")
            if not saved_path:
                saved_path = "workspace/file.txt"
            data = self.pending_write_artifacts.pop(
                saved_path, {"content": "", "mode": "write"}
            )
            ct = data.get("content") or ""
            aid = saved_path.replace("/", "_").replace(".", "_")
            a_type = (
                "html"
                if saved_path.endswith(".html")
                else "python"
                if saved_path.endswith(".py")
                else "text"
            )
            yield self._track_sse(
                {
                    "type": "artifact_start",
                    "artifact": {
                        "identifier": aid,
                        "type": a_type,
                        "title": f"📄 Artifact: {saved_path}",
                        "auto_execute": False,
                    },
                }
            )
            yield self._track_sse(
                {"type": "artifact_content", "content": ct, "artifact_id": aid}
            )
            yield self._track_sse(
                {
                    "type": "artifact_end",
                    "artifact": {
                        "identifier": aid,
                        "type": a_type,
                        "title": f"📄 Artifact: {saved_path}",
                        "path": saved_path,
                        "saved": True,
                        "version": 1,
                    },
                }
            )
            self.turn_persist.queue_attachment(
                storage_key=saved_path,
                original_name=Path(saved_path).name,
                mime=a_type,
                size_bytes=len(ct),
            )

        # --- mark_task_completed tool_end (plan execution) ---
        elif (
            evt.get("type") == "tool_end"
            and evt.get("name") == "mark_task_completed"
            and self._msg_src == "internal_trigger"
        ):
            self.stop_event.set()
            self.stop_reason = "plan_task_completed"
            outcome: Dict[str, Any] = {
                "type": "turn_outcome",
                "code": "plan_task_completed",
                "message": (
                    "Task marked completed. Turn interrupted — "
                    "the server will continue with the next task."
                ),
            }
            yield self._track_sse(outcome)

        # --- sandbox_edit_workspace_file tool_end ---
        elif (
            evt.get("type") == "tool_end"
            and evt.get("name") == "sandbox_edit_workspace_file"
        ):
            output_text = str(evt.get("output") or "")
            saved_path = ""
            try:
                out_data = json.loads(output_text)
                if isinstance(out_data, dict):
                    saved_path = str(out_data.get("file") or "")
            except Exception:
                pass
            if not saved_path:
                saved_path = "workspace/file.txt"
            data = self.pending_write_artifacts.pop(saved_path, {})
            if data.get("mode") == "edit":
                try:
                    from src.session_workspace import safe_resolve

                    p = safe_resolve(self.session_id, saved_path, must_exist=True)
                    updated_content = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    updated_content = f"[file updated: {saved_path}]"
                aid = saved_path.replace("/", "_").replace(".", "_") + "_edit"
                a_type = (
                    "python"
                    if saved_path.endswith(".py")
                    else "html"
                    if saved_path.endswith(".html")
                    else "text"
                )
                yield self._track_sse(
                    {
                        "type": "artifact_start",
                        "artifact": {
                            "identifier": aid,
                            "type": a_type,
                            "title": f"✏️ Edit: {saved_path}",
                            "auto_execute": False,
                        },
                    }
                )
                yield self._track_sse(
                    {
                        "type": "artifact_content",
                        "content": updated_content,
                        "artifact_id": aid,
                    }
                )
                yield self._track_sse(
                    {
                        "type": "artifact_end",
                        "artifact": {
                            "identifier": aid,
                            "type": a_type,
                            "title": f"✏️ Edit: {saved_path}",
                            "path": saved_path,
                            "saved": True,
                            "version": 1,
                        },
                    }
                )
                self.turn_persist.queue_attachment(
                    storage_key=saved_path,
                    original_name=Path(saved_path).name,
                    mime=a_type,
                    size_bytes=len(updated_content),
                )

        # --- Persistence of tool steps ---
        if evt.get("type") == "tool_start":
            self.turn_persist.queue_tool_step(evt, is_start=True)
            if self.assistant_message_id:
                await self.turn_persist.persist_pending_turn_records(
                    self.assistant_message_id,
                    only_new=True,
                    include_attachments=False,
                )
        elif evt.get("type") == "tool_end":
            try:
                call_id = str(evt.get("id") or "").strip()
                out_tokens = count_tokens(str(evt.get("output") or ""))
                inp_tokens = 0
                for ps in self.turn_persist.pending_db_steps:
                    if ps.get("step_id") == call_id:
                        inp_tokens = count_tokens(ps.get("input") or "")
                        break
                evt["tokens_in"] = inp_tokens
                evt["tokens_out"] = out_tokens
            except Exception as e:
                logger.warning("Failed to count tool tokens: %s", e)
            self.turn_persist.queue_tool_step(evt)
            if self.assistant_message_id:
                await self.turn_persist.persist_pending_turn_records(
                    self.assistant_message_id,
                    only_new=True,
                    include_attachments=False,
                )
        elif evt.get("type") == "tool_error":
            self.turn_persist.queue_tool_step(evt, is_error=True)
            if self.assistant_message_id:
                await self.turn_persist.persist_pending_turn_records(
                    self.assistant_message_id,
                    only_new=True,
                    include_attachments=False,
                )

        yield self._track_sse(chunk)

    # ------------------------------------------------------------------
    # Private: artifact finalizer (shared by token and tool_event)
    # ------------------------------------------------------------------

    async def _finalize_artifact(self, pe: Any) -> AsyncGenerator[Dict[str, Any], None]:
        from src.agent_pipeline import (
            _is_plan_artifact_payload,
            _plan_artifact_sse_end,
            _resolve_turn_plan_id,
            _setup_plan_artifact_chunk,
        )

        if _is_plan_artifact_payload(
            pe.artifact_id or "",
            pe.artifact_type or "",
            pe.content or "",
        ):
            _pid = _resolve_turn_plan_id(self.plan_controller, pe.artifact_id)
            pending = await _setup_plan_artifact_chunk(
                session_id=self.session_id,
                user_id=self.user_id,
                artifact_id=_pid,
                markdown_content=pe.content or "",
            )
            yield self._track_sse(
                {
                    "type": "artifact_end",
                    "artifact": _plan_artifact_sse_end(pe, plan_id=_pid),
                }
            )
            if pending:
                yield self._track_sse(pending)
        else:
            path, version = self.artifact_manager.save(
                pe.artifact_id,
                pe.content,
                pe.artifact_type,
                pe.filename,
            )
            root = self.artifact_manager._root
            res: Dict[str, Any] = {
                "type": "artifact_end",
                "artifact": {
                    "identifier": pe.artifact_id,
                    "type": pe.artifact_type or "text",
                    "title": pe.artifact_title,
                    "path": str(path.relative_to(root)),
                    "version": version,
                    "saved": True,
                },
            }
            if pe.auto_execute and path.suffix == ".py":
                res["artifact"]["execution"] = (
                    self.artifact_manager.auto_execute_sandboxed(path)
                )
            self.turn_persist.queue_attachment(
                storage_key=str(path.relative_to(root)),
                original_name=pe.filename or pe.artifact_id,
                mime=pe.artifact_type or "text/plain",
                size_bytes=len(pe.content or ""),
            )
            yield self._track_sse(res)

    # ------------------------------------------------------------------
    # Private: budget guard checker
    # ------------------------------------------------------------------

    def _check_budget_guards(self, ctype: str) -> Optional[Dict[str, Any]]:
        """Return an error event if any hard-stop budget is exceeded, else None."""
        if self.max_stream_events > 0 and self.stream_events > self.max_stream_events:
            self.stop_event.set()
            self.stop_reason = "stream_events_limit"
            return {
                "type": "error",
                "content": (
                    "Interrotto automaticamente: superato budget eventi turno "
                    f"({self.stream_events}/{self.max_stream_events})."
                ),
            }
        if (
            self.max_control_events > 0
            and self.control_events > self.max_control_events
        ):
            self.stop_event.set()
            self.stop_reason = "control_events_limit"
            return {
                "type": "error",
                "content": (
                    "Interrotto automaticamente: troppi eventi di controllo nel turno "
                    f"({self.control_events}/{self.max_control_events})."
                ),
            }
        if self.max_output_events > 0 and self.output_events > self.max_output_events:
            self.stop_event.set()
            self.stop_reason = "output_events_limit"
            return {
                "type": "error",
                "content": (
                    "Interrotto automaticamente: superato limite output eventi turno "
                    f"({self.output_events}/{self.max_output_events})."
                ),
            }
        if self.max_output_chars > 0 and self.output_chars > self.max_output_chars:
            self.stop_event.set()
            self.stop_reason = "output_chars_limit"
            return {
                "type": "error",
                "content": (
                    "Interrotto automaticamente: superato limite output caratteri turno "
                    f"({self.output_chars}/{self.max_output_chars})."
                ),
            }
        if (
            self.no_progress_timeout > 0
            and (self.loop.time() - self.last_progress_at) > self.no_progress_timeout
        ):
            self.stop_event.set()
            self.stop_reason = "no_progress_timeout"
            return {
                "type": "error",
                "content": (
                    "Automatically stopped: no progress detected in turn "
                    f"({int(self.no_progress_timeout)}s)."
                ),
            }
        return None


# ---------------------------------------------------------------------------
# Sentinel used internally to signal "break the outer loop"
# ---------------------------------------------------------------------------


class _BreakSignal:
    """Internal sentinel yielded by sub-handlers to request a loop break."""
