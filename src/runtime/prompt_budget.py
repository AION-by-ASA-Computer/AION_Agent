"""Token budget per prompt injection layer (P1.3)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LAYER_BUDGETS: Dict[str, int] = {
    "ltm": 1200,
    "skills": 800,
    "operational_summary": 600,
    "workspace_manifest": 500,
    "orchestration_context": 500,
    "sql_query_memory": 400,
    "mempalace_nav": 400,
    "project_context": 400,
    "session_entity_cache": 300,
    "exploration_reminder": 200,
    "turn_state_reminder": 200,
    "plan_reminder": 300,
}


def _total_budget() -> int:
    raw = (os.getenv("AION_PROMPT_LAYER_TOTAL_BUDGET") or "6000").strip()
    try:
        return max(500, int(raw))
    except ValueError:
        return 6000


@dataclass
class PromptLayer:
    name: str
    text: str
    priority: int = 50
    max_tokens: int = 500


@dataclass
class PromptBudget:
    layers: List[PromptLayer] = field(default_factory=list)
    total_budget: int = field(default_factory=_total_budget)
    dropped: List[str] = field(default_factory=list)

    def add_layer(self, name: str, text: str, *, priority: int = 50) -> None:
        body = (text or "").strip()
        if not body:
            return
        cap = _DEFAULT_LAYER_BUDGETS.get(name, 400)
        self.layers.append(
            PromptLayer(name=name, text=body, priority=priority, max_tokens=cap)
        )

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def build(self) -> str:
        """Assemble layers by priority, truncating to total budget."""
        ordered = sorted(self.layers, key=lambda x: x.priority)
        parts: List[str] = []
        used = 0
        for layer in ordered:
            est = min(self._estimate_tokens(layer.text), layer.max_tokens)
            if used + est > self.total_budget:
                self.dropped.append(layer.name)
                logger.info("prompt_layer_dropped layer=%s reason=budget", layer.name)
                continue
            parts.append(layer.text)
            used += est
        if self.dropped:
            logger.info(
                "prompt_budget dropped_layers=%s used_tokens~%s", self.dropped, used
            )
        return "\n\n".join(parts)


_LAYER_PRIORITY: Dict[str, int] = {
    "plan_artifact_reminder": 5,
    "ltm_wake": 15,
    "sql_query_memory": 25,
    "mempalace_nav": 30,
    "project_context": 35,
    "session_entity_cache": 40,
    "operational_augment": 45,
    "exploration_reminder": 70,
    "turn_state_reminder": 75,
    "plan_reminder": 80,
}

_SKIP_BUDGET_KEYS = frozenset(
    {
        "user_input_raw",
        "user_input_after_nudge",
        "attachments_block",
        "plan_mode_skill_hint",
        "skill_discovery_nudge",
    }
)


def apply_injection_budget(
    core_text: str,
    inject_layers: List[Dict[str, str]],
) -> str:
    """
    Re-assemble prepended injection layers under token budget.
    ``core_text`` (user turn body) is never truncated.
    """
    core = (core_text or "").strip()
    if not inject_layers:
        return core
    budget = PromptBudget()
    for entry in inject_layers:
        key = str(entry.get("key") or "").strip()
        text = str(entry.get("text") or "").strip()
        if not key or not text or key in _SKIP_BUDGET_KEYS:
            continue
        budget.add_layer(key, text, priority=_LAYER_PRIORITY.get(key, 50))
    prefix = budget.build().strip()
    if not prefix:
        return core
    return f"{prefix}\n\n{core}"
