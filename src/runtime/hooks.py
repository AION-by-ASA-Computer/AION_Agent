from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("aion.hooks")

HookHandler = Callable[["HookContext"], Awaitable[None]]


@dataclass
class HookContext:
    event: str
    tenant_id: str
    conversation_id: Optional[str]
    user_id: Optional[str]
    profile: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    modified_payload: Optional[Dict[str, Any]] = None
    block: bool = False
    block_reason: Optional[str] = None


class HookRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[tuple[int, HookHandler]]] = {}

    def register(self, event: str, handler: HookHandler, priority: int = 50) -> None:
        self._handlers.setdefault(event, []).append((priority, handler))
        self._handlers[event].sort(key=lambda x: x[0])

    async def dispatch(self, event: str, ctx: HookContext) -> HookContext:
        for _, h in self._handlers.get(event, []):
            try:
                await h(ctx)
            except Exception as e:
                logger.warning("hook %s error: %s", event, e)
            if ctx.block:
                break
        return ctx


hook_registry = HookRegistry()
