"""Circuit breaker for repeated tool preflight failures within one session."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.tool_circuit")

_FAIL_COUNTS: Dict[str, int] = {}

_CIRCUIT_TOOLS = frozenset(
    {
        "sandbox_write_workspace_file",
        "sandbox_append_workspace_file",
        "sandbox_edit_workspace_file",
        "sandbox_apply_patch",
    }
)


def circuit_breaker_enabled() -> bool:
    raw = os.getenv("AION_TOOL_CIRCUIT_BREAKER_ENABLED")
    if raw is not None and str(raw).strip() != "":
        return raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        from src.settings import get_settings

        return bool(get_settings().tool_circuit_breaker_enabled)
    except Exception:
        return False


def _max_repeat() -> int:
    raw = (
        os.getenv("AION_TOOL_CIRCUIT_BREAKER_MAX")
        or os.getenv("AION_PI_TOOL_CIRCUIT_BREAKER_MAX")
        or ""
    ).strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    try:
        from src.settings import get_settings

        return max(1, int(get_settings().tool_circuit_breaker_max))
    except Exception:
        return 3


def _failure_key(
    session_id: str, tool_name: str, args: Dict[str, Any], error_code: str
) -> str:
    rel = str(args.get("relative_path") or "").strip() or "(no-path)"
    return f"{session_id}|{tool_name}|{rel}|{error_code}"


def _parse_error_code(error_json: str) -> str:
    try:
        data = json.loads(error_json)
        if isinstance(data, dict):
            return str(data.get("error") or "tool_error")
    except json.JSONDecodeError:
        pass
    return "tool_error"


def maybe_block_repeat_preflight(
    session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Optional[str]:
    """Return a circuit-breaker JSON error when the same preflight failed too often."""
    if not circuit_breaker_enabled():
        return None
    base = (tool_name or "").split("-")[-1].strip().lower()
    if base not in _CIRCUIT_TOOLS:
        return None
    for err_code in ("missing_arguments", "tool_args_truncated"):
        key = _failure_key(session_id, base, arguments, err_code)
        if _FAIL_COUNTS.get(key, 0) >= _max_repeat():
            rel = str(arguments.get("relative_path") or "").strip() or "(no-path)"
            logger.warning(
                "tool circuit breaker open session=%s tool=%s path=%s error=%s count=%s",
                (session_id or "")[:12],
                tool_name,
                rel,
                err_code,
                _max_repeat(),
            )
            return json.dumps(
                {
                    "ok": False,
                    "error": "circuit_breaker",
                    "tool": tool_name,
                    "relative_path": rel,
                    "message": (
                        f"Stopped retrying {tool_name} on {rel}: identical preflight "
                        f"failure ({err_code}) occurred {_max_repeat()} times. "
                        "Use a smaller script, sandbox_edit_workspace_file for patches, "
                        "or lower reasoning effort to avoid truncated tool JSON."
                    ),
                    "prior_error": err_code,
                },
                ensure_ascii=False,
            )
    return None


def record_preflight_failure(
    session_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    error_json: str,
) -> None:
    if not circuit_breaker_enabled():
        return
    base = (tool_name or "").split("-")[-1].strip().lower()
    if base not in _CIRCUIT_TOOLS:
        return
    err_code = _parse_error_code(error_json)
    if err_code not in ("missing_arguments", "tool_args_truncated"):
        return
    key = _failure_key(session_id, base, arguments, err_code)
    _FAIL_COUNTS[key] = _FAIL_COUNTS.get(key, 0) + 1


def reset_session_circuit(session_id: str) -> None:
    prefix = f"{session_id}|"
    for key in list(_FAIL_COUNTS):
        if key.startswith(prefix):
            del _FAIL_COUNTS[key]
