"""Append-only turn event log (foundation for SSE/DB/context parity)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TurnEventLog:
    turn_id: str
    events: List[Dict[str, Any]] = field(default_factory=list)

    def append(self, event: Dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("ts", time.time())
        self.events.append(payload)

    def tool_events(self) -> List[Dict[str, Any]]:
        return [e for e in self.events if e.get("type", "").startswith("tool")]


_logs: Dict[str, TurnEventLog] = {}


def get_turn_event_log(turn_id: str) -> TurnEventLog:
    if turn_id not in _logs:
        _logs[turn_id] = TurnEventLog(turn_id=turn_id)
    return _logs[turn_id]


def clear_turn_event_log(turn_id: str) -> None:
    _logs.pop(turn_id, None)
