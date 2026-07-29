"""Transform transcript before LLM conversion (Pi transformContext)."""

from __future__ import annotations

from typing import Callable, List, Optional

from src.runtime.messages.types import AionMessage

TransformHook = Callable[[List[AionMessage]], List[AionMessage]]


def transform_context(
    messages: List[AionMessage],
    hooks: Optional[List[TransformHook]] = None,
) -> List[AionMessage]:
    current = list(messages)
    for hook in hooks or []:
        try:
            current = hook(current)
        except Exception:
            continue
    return [m for m in current if m.role != "internal"]
