"""AION harness message model (Pi-inspired two-layer transcript)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

AionRole = Literal[
    "user",
    "assistant",
    "tool_result",
    "injection",
    "compaction_summary",
    "internal",
]

InjectionLayer = Literal[
    "ltm",
    "memory",
    "skill_nudge",
    "plan",
    "workspace",
    "attachments",
    "hooks",
    "other",
]


@dataclass
class AionMessage:
    role: AionRole
    content: str
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def injection_layer(self) -> Optional[str]:
        if self.role != "injection":
            return None
        return str(self.meta.get("layer") or "other")

    @property
    def tool_call_id(self) -> Optional[str]:
        return self.meta.get("tool_call_id")

    @property
    def tool_name(self) -> Optional[str]:
        return self.meta.get("tool_name")


_INJECTION_WRAPPERS: Dict[str, tuple[str, str]] = {
    "ltm": ("<ltm_context>", "</ltm_context>"),
    "memory": ("<memory_context>", "</memory_context>"),
    "skill_nudge": ("<skill_nudge>", "</skill_nudge>"),
    "plan": ("<plan_context>", "</plan_context>"),
    "workspace": ("<workspace_context>", "</workspace_context>"),
    "attachments": ("<attachments>", "</attachments>"),
    "hooks": ("<injection>", "</injection>"),
    "other": ("<context>", "</context>"),
}


def wrap_injection_text(layer: str, text: str) -> str:
    open_tag, close_tag = _INJECTION_WRAPPERS.get(layer, _INJECTION_WRAPPERS["other"])
    body = (text or "").strip()
    if not body:
        return ""
    return f"{open_tag}\n{body}\n{close_tag}"


def wrap_compaction_summary(text: str) -> str:
    from src.memory.context_compressor import format_compaction_block

    return format_compaction_block(text)
