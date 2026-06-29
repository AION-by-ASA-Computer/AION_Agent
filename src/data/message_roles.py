from __future__ import annotations

UI_VISIBLE_ROLES = frozenset({"user", "assistant"})
MODEL_CONTEXT_ROLES = frozenset({"user", "assistant"})
INTERNAL_ROLES = frozenset(
    {"system", "tool", "internal", "developer", "skill", "reasoning"}
)

INTERNAL_CONTENT_MARKERS = (
    "Role: Orchestrator",
    "Skills and rules",
    "Golden Rules",
    "Artifact Protocol",
    "Orchestration and HITL",
    "Sequential Mode (Anti-loop)",
    # Legacy Italian markers (older persisted sessions)
    "Ruolo: Orchestrator",
    "Competenze e Regole",
    "Regole d'Oro",
    "Orchestrazione e HITL sui piani",
    "Modalità Sequenziale (anti-loop)",
)


def normalize_message_role(role: str | None) -> str:
    r = (role or "").strip().lower()
    if r in UI_VISIBLE_ROLES:
        return r
    if r in INTERNAL_ROLES:
        return r
    if not r:
        return "internal"
    return "internal"


def is_ui_visible_role(role: str | None) -> bool:
    return normalize_message_role(role) in UI_VISIBLE_ROLES


def is_model_context_role(role: str | None) -> bool:
    return normalize_message_role(role) in MODEL_CONTEXT_ROLES


def looks_like_internal_content(content: str | None) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    return any(marker.lower() in text.lower() for marker in INTERNAL_CONTENT_MARKERS)


def looks_like_raw_plan_content(content: str | None) -> bool:
    text = (content or "").strip().lower()
    if not text:
        return False
    return text.startswith("<plan>") and text.endswith("</plan>")


def is_empty_technical_message(role: str | None, content: str | None) -> bool:
    nr = normalize_message_role(role)
    if nr not in {"assistant", "tool", "internal", "system"}:
        return False
    return not (content or "").strip()
