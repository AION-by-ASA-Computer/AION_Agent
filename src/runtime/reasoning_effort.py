"""Mappa il dropdown UI ``min|medium|max`` nello sforzo nativo del motore.

Flusso: chat-ui → FastAPI ``reasoning_effort`` → questo modulo → Haystack
``generation_kwargs`` → LiteLLM → OpenAI SDK → vLLM / API del modello.

Non è un flag solo Qwen3.8. **Ogni** modello in turno riceve i campi nativi;
cambia solo la *stringa* accettata dal motore (``high`` vs ``xhigh``, ecc.).

Rilevazione (automatica, niente env): si legge l'id del modello sul generatore
(``chat_generator.model``, es. ``Qwen/Qwen3.8-Flash-Next`` o ``openai/o3-mini``).

La chat-ui ha **Disattiva** (thinking off) e **min / medium / max** (thinking on).
Non coincidono: ``min`` è sforzo basso (``low``), non lo spegnimento.

| Famiglia | off (toggle) | min | medium | max |
|----------|--------------|-----|--------|-----|
| vLLM / OpenAI-compat (default) | ``enable_thinking=false`` (niente ``none``/``high``) | ``low`` | ``medium`` | ``xhigh`` |
| OpenAI o-series | ``low`` | ``low`` | ``medium`` | ``high`` |
| GPT-5 / gpt-oss | ``none`` | ``low`` | ``medium`` | ``xhigh`` |
| Anthropic / Google | thinking off | thinking on (budget basso) | thinking on | thinking on |

``AION_NATIVE_REASONING_DIALECT`` e ``AION_NATIVE_REASONING_EFFORT_VALUES``
sono override rari. Lasciarli vuoti: il default vLLM è già ``low|medium|xhigh``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Literal, Optional, Tuple

logger = logging.getLogger("aion.reasoning_effort")

ReasoningEffortLevel = Literal["min", "medium", "max"]
TurnReasoningLevel = Literal["off", "min", "medium", "max"]
ReasoningDialect = Literal["qwen38", "vllm", "openai_reasoning"]

_LEVELS = frozenset({"min", "medium", "max"})
_TURN_LEVELS = frozenset({"off", "min", "medium", "max"})
_DIALECTS = frozenset({"qwen38", "vllm", "openai_reasoning"})

# OpenAI Chat Completions / SDK: none, minimal, low, medium, high, xhigh, max.
_NATIVE_OPENAI_SDK = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)

# Qwen3.8 (Flash-Next, 27B, …): template accetta solo xhigh|medium|low.
# Non confondere con Qwen3-8B (otto miliardi).
_QWEN38_RE = re.compile(
    r"qwen[-_.]?3\.8|qwen3(?:\.8|_8)(?:\D|$)|qwen38(?:\D|$)|flash[-_]?next",
    re.IGNORECASE,
)
_OPENAI_GPT5_RE = re.compile(
    r"(?:^|/)(gpt-5|gpt-oss)(?:\b|[-_/])",
    re.IGNORECASE,
)
_OPENAI_O_SERIES_RE = re.compile(
    r"(?:^|/)(o1|o3|o4)(?:\b|[-_/])",
    re.IGNORECASE,
)

# vLLM Qwen 3.5/3.8 (anche con served-model-name custom) rifiuta ``high``/``none``.
_SCALE_QWEN38: Tuple[str, ...] = ("low", "medium", "xhigh")
_SCALE_COMPAT: Tuple[str, ...] = ("low", "medium", "xhigh")
_SCALE_O_SERIES: Tuple[str, ...] = ("low", "medium", "high")
_SCALE_GPT5: Tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)


def normalize_reasoning_effort(value: Optional[str]) -> ReasoningEffortLevel:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "medium"
    v = str(value).strip().lower()
    if v in _LEVELS:
        return v  # type: ignore[return-value]
    return "medium"


def normalize_turn_reasoning(value: Optional[str]) -> TurnReasoningLevel:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "medium"
    v = str(value).strip().lower()
    if v in ("off", "none", "disabled"):
        return "off"
    if v in _TURN_LEVELS:
        return v  # type: ignore[return-value]
    return "medium"


def resolve_turn_reasoning(
    request_effort: Optional[str],
    thinking_enabled: Optional[bool] = None,
) -> TurnReasoningLevel:
    """Combina toggle Thinking e dropdown min/medium/max.

    ``thinking_enabled=False`` → ``off``.
    ``thinking_enabled=True`` + ``min`` → sforzo ``low`` (thinking acceso).
    Toggle assente (client legacy): ``min`` resta spegnimento.
    """
    if thinking_enabled is False:
        return "off"
    effort = effective_reasoning_effort(request_effort)
    if thinking_enabled is True:
        return effort
    if effort == "min":
        return "off"
    return effort


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


def _parse_positive_int(raw: Optional[str]) -> Optional[int]:
    text = (raw or "").strip()
    if not text or text.lower() in ("0", "off", "false", "no"):
        return None
    try:
        n = int(text)
    except ValueError:
        return None
    return n if n > 0 else None


def _env_native_scale() -> Optional[Tuple[str, ...]]:
    raw = (os.getenv("AION_NATIVE_REASONING_EFFORT_VALUES") or "").strip()
    if not raw:
        return None
    values = tuple(part.strip().lower() for part in raw.split(",") if part.strip())
    return values or None


def _env_dialect() -> Optional[ReasoningDialect]:
    raw = (os.getenv("AION_NATIVE_REASONING_DIALECT") or "").strip().lower()
    if raw in _DIALECTS:
        return raw  # type: ignore[return-value]
    return None


def _model_id(model: Optional[str]) -> str:
    text = (model or "").strip()
    if text:
        return text
    return (os.getenv("AION_MODEL") or os.getenv("OPENAI_MODEL") or "").strip()


def detect_reasoning_dialect(
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> ReasoningDialect:
    """Famiglia di scala nativa. Default: OpenAI-compat (tutti i modelli)."""
    forced = _env_dialect()
    if forced:
        return forced

    provider_l = (provider or "").strip().lower()
    if provider_l in ("anthropic", "google"):
        return "vllm"

    model_l = _model_id(model).lower()
    if _OPENAI_GPT5_RE.search(model_l) or _OPENAI_O_SERIES_RE.search(model_l):
        return "openai_reasoning"
    if _QWEN38_RE.search(model_l):
        return "qwen38"
    return "vllm"


def native_reasoning_scale(
    dialect: ReasoningDialect,
    *,
    model: Optional[str] = None,
) -> Tuple[str, ...]:
    override = _env_native_scale()
    if override:
        return override
    if dialect == "qwen38":
        return _SCALE_QWEN38
    if dialect == "openai_reasoning":
        blob = _model_id(model).lower()
        if _OPENAI_GPT5_RE.search(blob):
            return _SCALE_GPT5
        return _SCALE_O_SERIES
    return _SCALE_COMPAT


def map_native_reasoning_effort(
    effort: TurnReasoningLevel,
    dialect: ReasoningDialect,
    *,
    model: Optional[str] = None,
) -> Optional[str]:
    """Traduce off/min/medium/max nel valore accettato dal motore.

    ``None`` = non inviare il campo nativo (thinking off via ``enable_thinking``).
    vLLM Qwen rifiuta ``none`` e ``high`` nel chat template: max è ``xhigh``.
    """
    values = native_reasoning_scale(dialect, model=model)
    thinking_vals = [v for v in values if v not in ("none", "minimal")]
    if effort == "off":
        if dialect == "openai_reasoning":
            return values[0] if values else "low"
        return None
    if effort == "min":
        if thinking_vals:
            return thinking_vals[0]
        return "low"
    if effort == "medium":
        if "medium" in values:
            return "medium"
        if not thinking_vals:
            return None
        return thinking_vals[len(thinking_vals) // 2]
    if not thinking_vals:
        return None
    return thinking_vals[-1]


def _thinking_token_budget_for_effort(effort: TurnReasoningLevel) -> Optional[int]:
    """Tetto hard vLLM. Nessun default: solo env esplicito.

    ``AION_REASONING_EFFORT_MAX_BUDGET`` vale solo per effort ``max``.
    ``AION_THINKING_TOKEN_BUDGET`` globale non si applica a ``min`` (usa
    ``AION_THINKING_TOKEN_BUDGET_MIN`` se serve un tetto dedicato).
    """
    if effort in ("off", "min"):
        min_budget = _parse_positive_int(os.getenv("AION_THINKING_TOKEN_BUDGET_MIN"))
        if min_budget is not None:
            return min_budget
        return None

    global_budget = _parse_positive_int(os.getenv("AION_THINKING_TOKEN_BUDGET"))
    if global_budget is not None:
        return global_budget
    if effort == "max":
        for key in (
            "AION_REASONING_EFFORT_MAX_BUDGET",
            "AION_THINKING_TOKEN_BUDGET_MAX",
        ):
            parsed = _parse_positive_int(os.getenv(key))
            if parsed is not None:
                return parsed
    elif effort == "medium":
        parsed = _parse_positive_int(os.getenv("AION_THINKING_TOKEN_BUDGET_MEDIUM"))
        if parsed is not None:
            return parsed
    return None


def _strip_vllm_thinking_fields(extra_body: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(extra_body)
    cleaned.pop("chat_template_kwargs", None)
    cleaned.pop("enable_thinking", None)
    cleaned.pop("preserve_thinking", None)
    cleaned.pop("reasoning_effort", None)
    cleaned.pop("thinking_token_budget", None)
    return cleaned


def _ensure_allowed_openai_param(out: Dict[str, Any], name: str) -> None:
    """Haystack LiteLLM sets drop_params=True; without this, non-catalog models drop top-level reasoning_effort."""
    existing = out.get("allowed_openai_params")
    if existing is None:
        out["allowed_openai_params"] = [name]
        return
    if isinstance(existing, (list, tuple, set)):
        vals = [str(v) for v in existing]
        if name not in vals:
            vals.append(name)
        out["allowed_openai_params"] = vals


def _apply_openai_reasoning_kwargs(
    base: Dict[str, Any],
    native: Optional[str],
) -> Dict[str, Any]:
    out = dict(base or {})
    if native:
        out["reasoning_effort"] = native
        _ensure_allowed_openai_param(out, "reasoning_effort")
    else:
        out.pop("reasoning_effort", None)
    eb = out.get("extra_body")
    if isinstance(eb, dict):
        cleaned = _strip_vllm_thinking_fields(eb)
        if cleaned:
            out["extra_body"] = cleaned
        else:
            out.pop("extra_body", None)
    return out


def _apply_native_effort_fields(
    out: Dict[str, Any],
    eb: Dict[str, Any],
    ctk: Dict[str, Any],
    native: Optional[str],
) -> None:
    if native is not None:
        if native in _NATIVE_OPENAI_SDK:
            out["reasoning_effort"] = native
            _ensure_allowed_openai_param(out, "reasoning_effort")
        else:
            out.pop("reasoning_effort", None)
        eb["reasoning_effort"] = native
        ctk["reasoning_effort"] = native
        return
    out.pop("reasoning_effort", None)
    eb.pop("reasoning_effort", None)
    ctk.pop("reasoning_effort", None)


def _apply_budget_provider_kwargs(
    base: Dict[str, Any],
    effort: TurnReasoningLevel,
) -> Dict[str, Any]:
    """Anthropic / Gemini: lo sforzo nativo è thinking + budget_tokens."""
    out = dict(base or {})
    if effort == "off":
        out.pop("thinking", None)
        return out
    budget = _thinking_token_budget_for_effort(effort)
    if budget is None:
        budget = {"min": 512, "medium": 1024, "max": 4096}.get(effort, 1024)
    out["thinking"] = {"type": "enabled", "budget_tokens": budget}
    max_tokens = out.get("max_tokens") or 8192
    if max_tokens <= budget:
        out["max_tokens"] = budget + 2048
    return out


def merge_generation_kwargs(
    base: Dict[str, Any],
    effort: TurnReasoningLevel,
    *,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    dialect = detect_reasoning_dialect(model, provider)
    native = map_native_reasoning_effort(effort, dialect, model=model)
    thinking_on = effort != "off"

    logger.debug(
        "reasoning_effort ui=%s dialect=%s native=%s thinking_on=%s model=%s",
        effort,
        dialect,
        native,
        thinking_on,
        model,
    )

    if dialect == "openai_reasoning":
        return _apply_openai_reasoning_kwargs(base, native)

    out = dict(base or {})
    eb = dict(out.get("extra_body") or {})
    ctk = dict(eb.get("chat_template_kwargs") or {})

    ctk["enable_thinking"] = thinking_on
    ctk["preserve_thinking"] = thinking_on
    eb["enable_thinking"] = thinking_on
    eb["preserve_thinking"] = thinking_on
    _apply_native_effort_fields(out, eb, ctk, native)

    if thinking_on:
        budget = _thinking_token_budget_for_effort(effort)
        if budget is not None:
            eb["thinking_token_budget"] = budget
        else:
            eb.pop("thinking_token_budget", None)
    else:
        eb.pop("thinking_token_budget", None)

    eb["chat_template_kwargs"] = ctk
    out["extra_body"] = eb
    return out


def generation_kwargs_for_agent(
    agent: Any, effort: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Ritorna kwargs completi per il turno (effort nativo su qualunque modello)."""
    e = normalize_turn_reasoning(effort)
    gen = getattr(agent, "chat_generator", None)
    base = (
        dict(getattr(gen, "generation_kwargs", None) or {}) if gen is not None else {}
    )

    if gen is None:
        return merge_generation_kwargs(base, e)

    provider = str(getattr(gen, "provider", "openai") or "openai").strip().lower()
    model = str(getattr(gen, "model", "") or "")
    dialect = detect_reasoning_dialect(model, provider)

    if provider in ("anthropic", "google"):
        return _apply_budget_provider_kwargs(base, e)

    if dialect == "openai_reasoning":
        native = map_native_reasoning_effort(e, dialect, model=model)
        return _apply_openai_reasoning_kwargs(base, native)

    return merge_generation_kwargs(base, e, model=model, provider=provider)
