"""Central typed settings (P1.6). Import src.aion_env before this module."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

try:
    from pydantic import Field, field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - dev without pydantic-settings
    BaseSettings = object  # type: ignore[misc, assignment]
    SettingsConfigDict = dict  # type: ignore[misc, assignment]

    def Field(*a, **k):
        return None

    def field_validator(*a, **k):
        return lambda fn: fn


class AionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AION_",
        env_file=".env",
        extra="ignore",
    )

    # LLM / API
    api_url: str = Field("", description="LLM endpoint URL (vLLM / OpenAI-compatible).")
    model: str = Field("", description="LLM model name passed in API requests.")
    llm_adapter: str = Field("vllm_qwen", description="LLM adapter identifier.")
    llm_timeout: int = Field(120, description="HTTP timeout (s) for LLM calls.")
    chat_max_tokens: int = Field(
        8192, description="Max response tokens per chat turn (AION_CHAT_MAX_TOKENS)."
    )
    default_reasoning_effort: str = Field(
        "",
        description=(
            "Default reasoning effort level: min | medium | max. "
            "Falls back to AION_THINKING_ENABLED when empty."
        ),
    )

    # Agent execution
    max_agent_steps: int = Field(15, description="Max Haystack agent loop iterations.")
    plan_mode_tool_first: bool = Field(
        True, description="In plan mode emit tool calls before plain text."
    )
    plan_text_parser: bool = Field(
        False, description="Enable plan-tag text parser for XML-based plan output."
    )
    stream_loop_v2: bool = Field(
        False,
        description="Enable v2 streaming loop with improved back-pressure handling.",
    )
    plan_finalizer_timeout_sec: float = Field(
        20.0, description="Timeout (s) waiting for plan finalizer step."
    )
    tool_calls_max_per_turn: int = Field(
        24, description="Hard cap on tool calls per agent turn."
    )
    stream_events_max_per_turn: int = Field(
        0, description="Cap on SSE stream events per turn (0 = unlimited)."
    )
    no_progress_timeout_sec: float = Field(
        90.0, description="Abort turn if no progress within this many seconds."
    )
    agent_exec_legacy_thread: bool = Field(
        False, description="Use legacy thread-based agent execution path."
    )
    cors_allow_wildcard: bool = Field(
        False, description="Allow wildcard (*) CORS origins (dev escape hatch)."
    )

    # STM / memory
    stm_max_turns: int = Field(
        10, description="Max conversation turns kept in STM window."
    )
    stm_token_budget: Optional[int] = Field(
        None,
        description="Optional token cap for STM window (overrides auto budget when set).",
    )
    context_compress_enabled: bool = Field(
        True,
        description="Enable automatic context compression when the token budget is exceeded.",
    )

    # Observability
    otel_enabled: bool = Field(
        False, description="Enable OpenTelemetry tracing/spans for agent turns."
    )

    # Web search
    web_search_require_client_opt_in: bool = Field(
        False,
        description=(
            "When True, web search is off unless the client explicitly opts in "
            "via the API request payload."
        ),
    )

    # MCP (P2.7)
    mcp_pool: bool = Field(
        True, description="Use persistent MCP stdio pool per session."
    )
    mcp_user_pool: bool = Field(
        True, description="Maintain a shared MCP worker pool keyed by user."
    )
    mcp_session_env_inject: bool = Field(
        False, description="Inject session env vars into MCP server subprocesses."
    )
    mcp_startup_warm: bool = Field(
        True, description="Pre-warm MCP connections at API startup."
    )
    mcp_warm_timeout_sec: float = Field(
        10.0, description="Timeout (s) for individual MCP warm connections."
    )
    mcp_list_tools_timeout_sec: float = Field(
        30.0, description="Timeout (s) for listing tools from an MCP server."
    )
    mcp_session_scoped_servers: str = Field(
        "session_sandbox,promo_render,ocr,ocr_mcp,skills_hub,memory,aion_subagents",
        description=(
            "Comma-separated MCP server names that get a dedicated worker per "
            "chat session (they read AION_CHAT_SESSION_ID at runtime)."
        ),
    )

    # Profiles (P2.1)
    profile_validate_strict: bool = Field(
        False, description="Raise on profile validation errors at startup."
    )
    profile_hot_reload: bool = Field(
        False, description="Reload profile YAML files on each request."
    )
    default_profile: str = Field("aion_std", description="Default agent profile slug.")
    profile_legacy_name_lookup: bool = Field(
        False, description="Fall back to legacy profile name resolution."
    )

    # Skills (P2.10)
    skill_distill_tool_log_max_chars: int = Field(
        8000, description="Max chars of tool log included in skill distillation prompt."
    )
    skill_view_metrics: bool = Field(
        True, description="Expose per-skill usage metrics in admin UI."
    )

    # ---------------------------------------------------------------------------
    # Validators — coerce empty-string env values to sensible typed defaults.
    # .env files often contain AION_STM_TOKEN_BUDGET= (empty) which pydantic
    # would otherwise reject for Optional[int] fields.
    # ---------------------------------------------------------------------------

    @field_validator("stm_token_budget", mode="before")
    @classmethod
    def _coerce_stm_token_budget(cls, v):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return v


@lru_cache(maxsize=1)
def get_settings() -> AionSettings:
    if BaseSettings is object:
        return AionSettings()  # type: ignore[call-arg]
    return AionSettings()


def env_or_settings(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read env with optional fallback to settings field (migration helper)."""
    val = os.getenv(name)
    if val is not None and str(val).strip() != "":
        return val
    if os.getenv("AION_SETTINGS_LEGACY_FALLBACK", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return default
    return default
