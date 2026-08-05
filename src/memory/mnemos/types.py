"""Shared types and constants for Mnemos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ScopeType = Literal["user", "project", "global"]
NoteCategory = Literal["preference", "fact", "event", "decision", "pitfall", "task"]
RecallMode = Literal["current", "historical"]

SCOPE_TYPES = frozenset({"user", "project", "global"})
NOTE_CATEGORIES = frozenset(
    {"preference", "fact", "event", "decision", "pitfall", "task"}
)
NOTE_STATUSES = frozenset({"active", "superseded"})

CONTENT_MAX_CHARS = 500
DIGEST_MAX_CHARS = 500


@dataclass(frozen=True)
class MemoryScope:
    tenant_id: str
    scope_type: str
    scope_key: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.scope_type, self.scope_key)
