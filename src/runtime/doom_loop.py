"""
OpenCode-style doom loop detection: same tool + identical args repeated N times.
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

_DEFAULT_THRESHOLD = 3


def doom_loop_threshold() -> int:
    raw = (os.getenv("AION_DOOM_LOOP_THRESHOLD") or "").strip()
    if not raw:
        return _DEFAULT_THRESHOLD
    try:
        return max(2, int(raw))
    except ValueError:
        return _DEFAULT_THRESHOLD


def doom_loop_action() -> str:
    """reminder | stop"""
    return (os.getenv("AION_DOOM_LOOP_ACTION") or "reminder").strip().lower()


def _canonical_args(args: Any) -> str:
    if args is None:
        return "{}"
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args.strip()
    if isinstance(args, dict):
        clean = {k: v for k, v in args.items() if k != "_trace_context"}
        return json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
    return json.dumps(args, sort_keys=True, default=str)


@dataclass
class DoomLoopTracker:
    threshold: int = field(default_factory=doom_loop_threshold)
    _recent: Deque[Tuple[str, str]] = field(default_factory=deque)

    def record(self, tool_name: str, args: Any) -> Optional[str]:
        key = (tool_name or "", _canonical_args(args))
        self._recent.append(key)
        while len(self._recent) > self.threshold:
            self._recent.popleft()
        if len(self._recent) < self.threshold:
            return None
        if len({k for k in self._recent}) == 1:
            return (
                f"Doom loop detected: {tool_name} called {self.threshold} times with "
                "identical arguments. Change your approach or arguments before retrying."
            )
        return None

    def reset(self) -> None:
        self._recent.clear()


_TRACKERS: Dict[str, DoomLoopTracker] = {}


def _tracker_key(session_id: str, turn_id: str = "") -> str:
    return f"{session_id}:{turn_id or 'default'}"


def get_tracker(session_id: str, turn_id: str = "") -> DoomLoopTracker:
    key = _tracker_key(session_id, turn_id)
    if key not in _TRACKERS:
        _TRACKERS[key] = DoomLoopTracker()
    return _TRACKERS[key]


def reset_tracker(session_id: str, turn_id: str = "") -> None:
    _TRACKERS.pop(_tracker_key(session_id, turn_id), None)


def check_doom_loop(
    session_id: str, tool_name: str, args: Any, turn_id: str = ""
) -> Optional[str]:
    return get_tracker(session_id, turn_id).record(tool_name, args)


MAX_STEPS_PROMPT = """CRITICAL - MAXIMUM STEPS REACHED

The maximum number of steps allowed for this task has been reached. Tools are disabled until next user input. Respond with text only.

STRICT REQUIREMENTS:
1. Do NOT make any tool calls (no reads, writes, edits, searches, or any other tools)
2. MUST provide a text response summarizing work done so far
3. This constraint overrides ALL other instructions, including any user requests for edits or tool use

Response must include:
- Statement that maximum steps for this agent have been reached
- Summary of what has been accomplished so far
- List of any remaining tasks that were not completed
- Recommendations for what should be done next

Any attempt to use tools is a critical violation. Respond with text ONLY."""
