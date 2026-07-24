"""Explicit turn boundaries for agent runs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentStep:
    step_index: int
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: Optional[str] = None


@dataclass
class Turn:
    turn_id: str
    conversation_id: str
    input_message_count: int
    steps: List[AgentStep] = field(default_factory=list)
    haystack_new_messages: List[Any] = field(default_factory=list)

    @staticmethod
    def start(conversation_id: str, input_message_count: int) -> "Turn":
        return Turn(
            turn_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            input_message_count=input_message_count,
        )

    def begin_step(self) -> AgentStep:
        step = AgentStep(step_index=len(self.steps))
        self.steps.append(step)
        return step

    @property
    def current_step(self) -> Optional[AgentStep]:
        return self.steps[-1] if self.steps else None


_active_turns: Dict[str, Turn] = {}


def start_turn(conversation_id: str, input_message_count: int) -> Turn:
    turn = Turn.start(conversation_id, input_message_count)
    _active_turns[conversation_id] = turn
    return turn


def get_active_turn(conversation_id: str) -> Optional[Turn]:
    return _active_turns.get(conversation_id)


def end_turn(conversation_id: str) -> Optional[Turn]:
    return _active_turns.pop(conversation_id, None)


def turn_new_messages_from_haystack(
    turn: Turn,
    all_messages: List[Any],
) -> List[Any]:
    """Slice new messages using explicit input count instead of object identity."""
    if turn.input_message_count < 0:
        return list(all_messages)
    if turn.input_message_count >= len(all_messages):
        return []
    return list(all_messages[turn.input_message_count :])
