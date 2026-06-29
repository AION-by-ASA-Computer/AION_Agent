"""In-process session context for MCP pool keys and profile gate (P2.6)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class SessionContext:
    profile_slug: str
    user_id: str
    tenant_id: str = "default"
    conversation_id: str = ""

    def as_tuple(self) -> Tuple[str, str, str]:
        return (self.profile_slug, self.user_id, self.tenant_id)

    @classmethod
    def from_tuple(cls, conversation_id: str, raw: Tuple[str, ...]) -> "SessionContext":
        if len(raw) == 2:
            slug, uid = raw
            tid = "default"
        else:
            slug, uid, tid = raw[0], raw[1], raw[2] if len(raw) > 2 else "default"
        return cls(
            profile_slug=slug,
            user_id=uid,
            tenant_id=(tid or "default").strip() or "default",
            conversation_id=conversation_id,
        )
