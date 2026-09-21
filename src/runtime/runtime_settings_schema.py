"""Allowlisted per-user runtime settings (chat-ui sidebar).

``.env`` / ``AionSettings`` supply the initial defaults. Secrets, URLs, and
free-form ``extra_body`` are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

RUNTIME_SETTINGS_META_KEY = "runtime_settings"
MAX_PRESETS_PER_USER = 20
PRESET_NAME_MAX_LEN = 40
HARD_MAX_AGENT_STEPS = 200
HARD_MAX_TOOL_CALLS = 200
HARD_MAX_TOOL_EVENTS = 500
HARD_MAX_TURN_TIMEOUT = 3600.0
HARD_MAX_TOKENS = 32768


@dataclass(frozen=True)
class RuntimeFieldSpec:
    key: str
    group: str
    kind: str  # int | float | bool | enum
    env_key: str
    fallback: Any
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    nullable: bool = False
    enum_values: Optional[Tuple[str, ...]] = None


RUNTIME_FIELDS: Tuple[RuntimeFieldSpec, ...] = (
    RuntimeFieldSpec(
        key="max_agent_steps",
        group="loop",
        kind="int",
        env_key="AION_MAX_AGENT_STEPS",
        fallback=15,
        min_value=1,
        max_value=HARD_MAX_AGENT_STEPS,
        step=1,
    ),
    RuntimeFieldSpec(
        key="max_tool_calls",
        group="loop",
        kind="int",
        env_key="AION_TOOL_CALLS_MAX_PER_TURN",
        fallback=24,
        min_value=1,
        max_value=HARD_MAX_TOOL_CALLS,
        step=1,
    ),
    RuntimeFieldSpec(
        key="max_tool_events",
        group="loop",
        kind="int",
        env_key="AION_TOOL_EVENTS_MAX_PER_TURN",
        fallback=60,
        min_value=1,
        max_value=HARD_MAX_TOOL_EVENTS,
        step=1,
    ),
    RuntimeFieldSpec(
        key="turn_timeout_sec",
        group="loop",
        kind="float",
        env_key="AION_AGENT_TURN_TIMEOUT",
        fallback=600.0,
        min_value=30.0,
        max_value=HARD_MAX_TURN_TIMEOUT,
        step=10,
    ),
    RuntimeFieldSpec(
        key="no_progress_timeout_sec",
        group="loop",
        kind="float",
        env_key="AION_NO_PROGRESS_TIMEOUT_SEC",
        fallback=90.0,
        min_value=10.0,
        max_value=HARD_MAX_TURN_TIMEOUT,
        step=5,
    ),
    RuntimeFieldSpec(
        key="max_tokens",
        group="generation",
        kind="int",
        env_key="AION_CHAT_MAX_TOKENS",
        fallback=8192,
        min_value=256,
        max_value=HARD_MAX_TOKENS,
        step=256,
    ),
    RuntimeFieldSpec(
        key="temperature",
        group="generation",
        kind="float",
        env_key="AION_TEMPERATURE",
        fallback=0.7,
        min_value=0.0,
        max_value=2.0,
        step=0.05,
    ),
    RuntimeFieldSpec(
        key="top_p",
        group="generation",
        kind="float",
        env_key="AION_TOP_P",
        fallback=1.0,
        min_value=0.0,
        max_value=1.0,
        step=0.05,
    ),
    RuntimeFieldSpec(
        key="top_k",
        group="generation",
        kind="int",
        env_key="AION_TOP_K",
        fallback=None,
        min_value=1,
        max_value=100,
        step=1,
        nullable=True,
    ),
    RuntimeFieldSpec(
        key="presence_penalty",
        group="generation",
        kind="float",
        env_key="AION_PRESENCE_PENALTY",
        fallback=None,
        min_value=-2.0,
        max_value=2.0,
        step=0.1,
        nullable=True,
    ),
    RuntimeFieldSpec(
        key="frequency_penalty",
        group="generation",
        kind="float",
        env_key="AION_FREQUENCY_PENALTY",
        fallback=None,
        min_value=-2.0,
        max_value=2.0,
        step=0.1,
        nullable=True,
    ),
    RuntimeFieldSpec(
        key="repetition_penalty",
        group="generation",
        kind="float",
        env_key="AION_REPETITION_PENALTY",
        fallback=None,
        min_value=0.5,
        max_value=2.0,
        step=0.05,
        nullable=True,
    ),
    RuntimeFieldSpec(
        key="seed",
        group="generation",
        kind="int",
        env_key="AION_SEED",
        fallback=None,
        min_value=0,
        max_value=2_147_483_647,
        step=1,
        nullable=True,
    ),
    RuntimeFieldSpec(
        key="thinking_enabled",
        group="thinking",
        kind="bool",
        env_key="AION_THINKING_ENABLED",
        fallback=True,
    ),
    RuntimeFieldSpec(
        key="reasoning_effort",
        group="thinking",
        kind="enum",
        env_key="AION_DEFAULT_REASONING_EFFORT",
        fallback="medium",
        enum_values=("min", "medium", "max"),
    ),
    RuntimeFieldSpec(
        key="thinking_token_budget",
        group="thinking",
        kind="int",
        env_key="AION_THINKING_TOKEN_BUDGET",
        fallback=None,
        min_value=64,
        max_value=65536,
        step=64,
        nullable=True,
    ),
    RuntimeFieldSpec(
        key="reasoning_hard_stop",
        group="thinking",
        kind="bool",
        env_key="AION_REASONING_HARD_STOP",
        fallback=False,
    ),
    RuntimeFieldSpec(
        key="reasoning_max_chars",
        group="advanced",
        kind="int",
        env_key="AION_REASONING_MAX_CHARS",
        fallback=20000,
        min_value=500,
        max_value=200000,
        step=500,
    ),
    RuntimeFieldSpec(
        key="reasoning_max_events",
        group="advanced",
        kind="int",
        env_key="AION_REASONING_MAX_EVENTS",
        fallback=240,
        min_value=10,
        max_value=2000,
        step=10,
    ),
    RuntimeFieldSpec(
        key="reasoning_min_chars",
        group="advanced",
        kind="int",
        env_key="AION_REASONING_MIN_CHARS",
        fallback=2000,
        min_value=200,
        max_value=50000,
        step=100,
    ),
    RuntimeFieldSpec(
        key="reasoning_min_events",
        group="advanced",
        kind="int",
        env_key="AION_REASONING_MIN_EVENTS",
        fallback=30,
        min_value=5,
        max_value=500,
        step=5,
    ),
    RuntimeFieldSpec(
        key="reasoning_max_level_chars",
        group="advanced",
        kind="int",
        env_key="AION_REASONING_MAX_LEVEL_CHARS",
        fallback=40000,
        min_value=500,
        max_value=400000,
        step=500,
    ),
    RuntimeFieldSpec(
        key="reasoning_max_level_events",
        group="advanced",
        kind="int",
        env_key="AION_REASONING_MAX_LEVEL_EVENTS",
        fallback=480,
        min_value=10,
        max_value=4000,
        step=10,
    ),
)

RUNTIME_FIELD_BY_KEY: Dict[str, RuntimeFieldSpec] = {f.key: f for f in RUNTIME_FIELDS}
RUNTIME_ALLOWLIST = frozenset(RUNTIME_FIELD_BY_KEY)

OPENAI_SAMPLING_KEYS = (
    "temperature",
    "top_p",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
    "seed",
)
VLLM_EXTRA_SAMPLING_KEYS = ("top_k", "repetition_penalty")

TURN_BUDGET_KEY_MAP = {
    "max_tool_calls": "max_tool_calls",
    "max_tool_events": "max_tool_events",
    "turn_timeout_sec": "turn_timeout",
    "no_progress_timeout_sec": "no_progress_timeout",
    "reasoning_max_chars": "max_reasoning_chars",
    "reasoning_max_events": "max_reasoning_events",
}


def schema_public() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spec in RUNTIME_FIELDS:
        row: Dict[str, Any] = {
            "key": spec.key,
            "group": spec.group,
            "type": spec.kind,
            "env_key": spec.env_key,
            "nullable": spec.nullable,
        }
        if spec.min_value is not None:
            row["min"] = spec.min_value
        if spec.max_value is not None:
            row["max"] = spec.max_value
        if spec.step is not None:
            row["step"] = spec.step
        if spec.enum_values:
            row["enum"] = list(spec.enum_values)
        out.append(row)
    return out
