"""
Recover from consecutive tool failures without ending the agent turn early.

When the model stops with a plain-text reply after repeated tool errors, an
``on_exit`` Haystack hook injects a system recovery prompt and sets
``continue_run`` so the agent gets another LLM step instead of giving up.
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

from haystack.dataclasses import ChatMessage, ChatRole

_DEFAULT_THRESHOLD = 2
_DEFAULT_MAX_RECOVERY_ATTEMPTS = 2


def tool_error_threshold() -> int:
    raw = (os.getenv("AION_TOOL_ERROR_THRESHOLD") or "").strip()
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_THRESHOLD


def tool_error_max_recovery_attempts() -> int:
    raw = (os.getenv("AION_TOOL_ERROR_MAX_RECOVERY") or "").strip()
    if not raw:
        return _DEFAULT_MAX_RECOVERY_ATTEMPTS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_MAX_RECOVERY_ATTEMPTS


@dataclass
class ToolErrorRecord:
    tool_name: str
    error: str


@dataclass
class ToolErrorTracker:
    threshold: int = field(default_factory=tool_error_threshold)
    consecutive_errors: int = 0
    _recent: Deque[ToolErrorRecord] = field(default_factory=lambda: deque(maxlen=5))

    def record_error(self, tool_name: str, error: str) -> bool:
        """Record a tool error. Returns True when threshold is reached."""
        self.consecutive_errors += 1
        self._recent.append(
            ToolErrorRecord(tool_name=tool_name or "tool", error=(error or "")[:500])
        )
        return self.consecutive_errors >= self.threshold

    def record_success(self) -> None:
        self.consecutive_errors = 0
        self._recent.clear()

    def reset(self) -> None:
        self.record_success()

    def recent_errors(self) -> List[ToolErrorRecord]:
        return list(self._recent)


_TRACKERS: Dict[str, ToolErrorTracker] = {}


def _tracker_key(session_id: str) -> str:
    return session_id or "default"


def get_tracker(session_id: str) -> ToolErrorTracker:
    key = _tracker_key(session_id)
    if key not in _TRACKERS:
        _TRACKERS[key] = ToolErrorTracker()
    return _TRACKERS[key]


def reset_tracker(session_id: str) -> None:
    _TRACKERS.pop(_tracker_key(session_id), None)


def record_tool_error(
    session_id: str, tool_name: str, error: str
) -> Optional[Dict[str, Any]]:
    """Track a tool error; return recovery status payload when threshold is hit."""
    tracker = get_tracker(session_id)
    threshold_hit = tracker.record_error(tool_name, error)
    if not threshold_hit:
        return None
    return {
        "consecutive_errors": tracker.consecutive_errors,
        "message": _build_status_message(tracker),
    }


def record_tool_success(session_id: str) -> None:
    get_tracker(session_id).record_success()


def _build_status_message(tracker: ToolErrorTracker) -> str:
    lines = [
        f"{tracker.consecutive_errors} consecutive tool call(s) failed.",
        "The agent will retry with adjusted arguments if it stops early.",
    ]
    for rec in tracker.recent_errors()[-3:]:
        err = rec.error.replace("\n", " ").strip()
        if len(err) > 160:
            err = err[:157] + "..."
        lines.append(f"- {rec.tool_name}: {err}")
    return " ".join(lines)


def build_recovery_prompt(tracker: ToolErrorTracker) -> str:
    """System prompt injected via on_exit when the model gives up after tool errors."""
    lines = [
        "SYSTEM RECOVERY — consecutive tool calls failed. Do NOT stop or summarize yet.",
        "You must continue working: read the errors below, change your approach, and call tools again.",
        "",
        "Recovery rules:",
        "1. Do NOT repeat the same failing call with identical arguments.",
        "2. Inspect related state first (list projects, list workspaces, read docs) if unsure.",
        "3. Fix validation issues (names, identifiers, required fields) before retrying.",
        "4. If a resource already exists, reuse or update it instead of creating a duplicate.",
        "5. Only respond with plain text when the task is done or you need user input.",
        "",
        "Recent tool errors:",
    ]
    for rec in tracker.recent_errors():
        err = rec.error.replace("\n", " ").strip()
        if len(err) > 240:
            err = err[:237] + "..."
        lines.append(f"- {rec.tool_name}: {err}")
    return "\n".join(lines)


def _turn_runtime_dict() -> Optional[Dict[str, Any]]:
    try:
        from src.runtime.turn_compaction import _turn_runtime
    except ImportError:
        return None
    if _turn_runtime is None:
        return None
    rt = _turn_runtime.get()
    return rt if isinstance(rt, dict) else None


def recover_from_consecutive_tool_errors(state: Any) -> None:
    """Haystack ``on_exit`` hook: keep running after text-exit following tool errors."""
    rt = _turn_runtime_dict()
    if rt is None:
        return
    session_id = str(rt.get("session_id") or "")
    tracker = get_tracker(session_id)
    if tracker.consecutive_errors < tracker.threshold:
        return
    attempts = int(rt.get("tool_error_recovery_attempts") or 0)
    if attempts >= tool_error_max_recovery_attempts():
        return

    messages = state.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    last = messages[-1]
    role = getattr(last, "role", None)
    role_val = str(role.value if hasattr(role, "value") else role or "").lower()
    has_tool_calls = bool(getattr(last, "tool_calls", None) or getattr(last, "tool_call", None))
    text = (getattr(last, "text", None) or "").strip()
    if role_val != ChatRole.ASSISTANT.value and role_val != "assistant":
        return
    if has_tool_calls or not text:
        return

    recovery_text = build_recovery_prompt(tracker)
    messages.append(ChatMessage.from_system(recovery_text))
    state.set("messages", messages)
    state.set("continue_run", True)
    rt["tool_error_recovery_attempts"] = attempts + 1


def get_default_agent_hooks() -> Dict[str, List[Any]]:
    """Hooks passed to Haystack Agent at construction time."""
    try:
        from haystack.hooks import hook

        @hook
        def tool_error_recovery_on_exit(state: Any) -> None:
            recover_from_consecutive_tool_errors(state)

        return {"on_exit": [tool_error_recovery_on_exit]}
    except ImportError:
        return {"on_exit": [recover_from_consecutive_tool_errors]}
