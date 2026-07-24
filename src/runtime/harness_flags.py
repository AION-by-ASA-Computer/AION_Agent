"""Feature flags for AION harness v2 (Pi-inspired patterns). All default off for safe rollout."""

from __future__ import annotations

import os


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def harness_v2_messages() -> bool:
    return _env_bool("AION_HARNESS_V2_MESSAGES")


def harness_v2_injections() -> bool:
    return _env_bool("AION_HARNESS_V2_INJECTIONS")


def harness_v2_compaction() -> bool:
    return _env_bool("AION_HARNESS_V2_COMPACTION")


def harness_v2_provider() -> bool:
    return _env_bool("AION_HARNESS_V2_PROVIDER")


def harness_v2_tools() -> bool:
    return _env_bool("AION_HARNESS_V2_TOOLS")


def harness_v2_turn() -> bool:
    return _env_bool("AION_HARNESS_V2_TURN")


def mid_turn_reasoning_compaction_enabled() -> bool:
    return _env_bool("AION_CONTEXT_COMPRESS_MID_TURN_REASONING", "0")


def mid_turn_sync_compaction_enabled() -> bool:
    """When false (default), mid-turn LLM summarization is skipped on the agent thread."""
    return _env_bool("AION_CONTEXT_COMPRESS_MID_TURN_SYNC", "0")


def stream_loop_legacy() -> bool:
    return _env_bool("AION_STREAM_LOOP_LEGACY", "0")


def tool_error_recovery_strict() -> bool:
    return _env_bool("AION_TOOL_ERROR_RECOVERY", "1")
