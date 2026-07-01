"""Normalize MCP tool outcomes for Haystack, SSE, and QueryMemory hooks."""

from __future__ import annotations

import json
import re
from typing import Any, Tuple

_SQL_ERROR_MARKERS = re.compile(
    r"(?i)(syntax error|does not exist|permission denied|invalid input|"
    r"column .* does not|relation .* does not|duplicate key|canceling statement|"
    r"failed to connect|connection refused|timeout expired|statement timeout|"
    r"canceling statement|deadlock detected)"
)


def format_mcp_raw_result(res: Any) -> str:
    """Extract text from MCP CallToolResult (or similar)."""
    if res is None:
        return ""
    if hasattr(res, "isError") and bool(getattr(res, "isError", False)):
        parts: list[str] = []
        if hasattr(res, "content") and res.content:
            for block in res.content:
                if hasattr(block, "text") and block.text:
                    parts.append(str(block.text))
        body = "\n".join(parts).strip()
        if body:
            return body
        return "MCP tool returned isError=true with no text content."
    if hasattr(res, "content") and res.content:
        return "\n".join(
            str(c.text) for c in res.content if hasattr(c, "text") and c.text
        )
    return str(res)


def _parse_json_error(text: str) -> Tuple[bool, str]:
    stripped = (text or "").strip()
    if not stripped.startswith("{"):
        return False, text
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return False, text
    if not isinstance(data, dict):
        return False, text
    if data.get("ok") is False or data.get("error"):
        err = data.get("error")
        if isinstance(err, dict):
            msg = (
                err.get("message")
                or err.get("detail")
                or json.dumps(err, ensure_ascii=False)
            )
            err_code = err.get("code") or "tool_error"
        else:
            msg = str(data.get("message") or "").strip()
            if not msg:
                msg = str(data.get("stderr") or data.get("stdout") or "").strip()
            if not msg and data.get("exit_code") is not None:
                msg = f"command failed with exit code {data.get('exit_code')}"
            if err:
                err_code = str(err)
            elif data.get("exit_code") is not None or msg:
                err_code = "exec_failed"
            else:
                err_code = "tool_error"
            if not msg:
                msg = err_code
        payload: dict[str, Any] = {
            "ok": False,
            "error": err_code,
            "message": msg[:8000],
        }
        if data.get("exit_code") is not None:
            payload["exit_code"] = data.get("exit_code")
        stderr = str(data.get("stderr") or "").strip()
        if stderr and stderr not in msg:
            payload["stderr"] = stderr[:8000]
        if data.get("command"):
            payload["command"] = data.get("command")
        hint = data.get("hint")
        if hint:
            payload["hint"] = hint
        return True, json.dumps(payload, ensure_ascii=False)
    return False, text


def classify_tool_result_text(text: str, tool_name: str = "") -> Tuple[bool, str]:
    """
    Return (is_error, normalized_text).
    Ensures SQL/MCP failures are visible to the LLM and UI even when no exception was raised.
    """
    raw = str(text or "")
    stripped = raw.strip()
    if not stripped:
        base = tool_name.split("-")[-1] if tool_name else tool_name
        if base in ("query", "execute_sql", "run_sql", "sql_query"):
            return True, json.dumps(
                {
                    "ok": False,
                    "error": "empty_tool_result",
                    "message": "Database tool returned an empty response (likely a failed query).",
                    "tool": tool_name or base,
                },
                ensure_ascii=False,
            )
        return False, raw

    is_json = False
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            is_json = True
        except json.JSONDecodeError:
            pass

    is_json_err, normalized = _parse_json_error(stripped)
    if is_json_err:
        return True, normalized
    if is_json:
        return False, raw

    low = stripped.lower()
    if "mcperror" in low or "mcp error" in low:
        return True, json.dumps(
            {
                "ok": False,
                "error": "mcperror",
                "message": stripped[:8000],
                "tool": tool_name,
            },
            ensure_ascii=False,
        )

    if stripped.startswith("Error:") or stripped.startswith("error:"):
        return True, json.dumps({"ok": False, "error": stripped}, ensure_ascii=False)

    if _SQL_ERROR_MARKERS.search(stripped):
        return True, json.dumps(
            {
                "ok": False,
                "error": "sql_execution_error",
                "message": stripped[:8000],
                "tool": tool_name,
            },
            ensure_ascii=False,
        )

    if low.startswith("ok\n") or low.startswith("ok\r"):
        return False, raw

    if "error" in low and ("exception" in low or "traceback" in low or "failed" in low):
        return True, json.dumps(
            {
                "ok": False,
                "error": "tool_runtime_error",
                "message": stripped[:8000],
                "tool": tool_name,
            },
            ensure_ascii=False,
        )

    return False, raw


def format_exception_for_tool(tool_name: str, exc: BaseException) -> str:
    """Structured error string returned to Haystack (instead of re-raising)."""
    payload: dict[str, Any] = {
        "ok": False,
        "error": type(exc).__name__,
        "message": str(exc) or repr(exc),
        "tool": tool_name,
    }
    return json.dumps(payload, ensure_ascii=False)
