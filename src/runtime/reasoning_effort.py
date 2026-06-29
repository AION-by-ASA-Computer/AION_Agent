"""Mappa `reasoning_effort` (per richiesta) in `generation_kwargs` completi per Haystack Agent.run.

OpenAIChatGenerator unisce con shallow merge: passare solo `extra_body` sovrascriverebbe il resto.
Qui si ricopia la base dal generatore e si aggiornano solo i rami necessari.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Literal, Optional

ReasoningEffortLevel = Literal["min", "medium", "max"]

_LEVELS = frozenset({"min", "medium", "max"})


def normalize_reasoning_effort(value: Optional[str]) -> ReasoningEffortLevel:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "medium"
    v = str(value).strip().lower()
    if v in _LEVELS:
        return v  # type: ignore[return-value]
    return "medium"


def effective_reasoning_effort(request_value: Optional[str]) -> ReasoningEffortLevel:
    """
    Livello usato per il turno API: se il client omette ``reasoning_effort`` (null),
    usa ``AION_DEFAULT_REASONING_EFFORT`` (min|medium|max) oppure, se assente,
    ``AION_THINKING_ENABLED`` (0/false/off → min, 1/true/on → medium), altrimenti medium.
    """
    if request_value is not None and str(request_value).strip() != "":
        return normalize_reasoning_effort(request_value)
    raw = (os.getenv("AION_DEFAULT_REASONING_EFFORT") or "").strip().lower()
    if raw in _LEVELS:
        return raw  # type: ignore[return-value]
    th = (os.getenv("AION_THINKING_ENABLED") or "").strip().lower()
    if th in ("0", "false", "no", "off"):
        return "min"
    if th in ("1", "true", "yes", "on"):
        return "medium"
    return "medium"


def _thinking_token_budget_for_effort(effort: ReasoningEffortLevel) -> Optional[int]:
    # 1. Global overrides
    for key in ("AION_THINKING_TOKEN_BUDGET", "AION_REASONING_EFFORT_MAX_BUDGET"):
        raw = (os.getenv(key) or "").strip()
        if raw and raw.lower() not in ("0", "off", "false", "no"):
            try:
                n = int(raw)
                if n > 0:
                    return n
            except ValueError:
                pass

    # 2. Effort-specific overrides
    if effort == "max":
        raw_max = os.getenv("AION_THINKING_TOKEN_BUDGET_MAX")
        if raw_max and raw_max.strip():
            try:
                n = int(raw_max)
                if n > 0:
                    return n
            except ValueError:
                pass
    elif effort == "medium":
        raw_med = os.getenv("AION_THINKING_TOKEN_BUDGET_MEDIUM")
        if raw_med and raw_med.strip():
            try:
                n = int(raw_med)
                if n > 0:
                    return n
            except ValueError:
                pass

    # 3. Dynamic defaults based on effort level
    if effort == "max":
        return 2048
    elif effort == "medium":
        return 1024
    return None


def merge_generation_kwargs(
    base: Dict[str, Any], effort: ReasoningEffortLevel
) -> Dict[str, Any]:
    out = dict(base or {})
    eb = dict(out.get("extra_body") or {})
    ctk = dict(eb.get("chat_template_kwargs") or {})

    if effort == "min":
        ctk["enable_thinking"] = False
        eb.pop("thinking_token_budget", None)
    else:
        ctk["enable_thinking"] = True
        budget = _thinking_token_budget_for_effort(effort)
        if budget is not None:
            eb["thinking_token_budget"] = budget
        else:
            eb.pop("thinking_token_budget", None)

    eb["chat_template_kwargs"] = ctk
    out["extra_body"] = eb
    return out


def generation_kwargs_for_agent(
    agent: Any, effort: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Ritorna kwargs completi per il turno (thinking esplicito + budget anche per medium)."""
    e = normalize_reasoning_effort(effort)
    gen = getattr(agent, "chat_generator", None)
    base = (
        dict(getattr(gen, "generation_kwargs", None) or {}) if gen is not None else {}
    )
    # extra_body è vLLM/OpenAI-specific — saltalo per altri provider (es. anthropic, google)
    if gen is not None and getattr(gen, "provider", "openai") not in (
        "openai",
        "azure",
    ):
        return base or None
    return merge_generation_kwargs(base, e)
