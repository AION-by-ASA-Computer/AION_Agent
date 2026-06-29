"""Queue tool steps for DB persistence during SSE streaming."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def queue_tool_step(
    pending_db_steps: List[Dict[str, Any]],
    pending_step_ids: Dict[str, str],
    evt: Dict[str, Any],
    *,
    is_error: bool = False,
    is_start: bool = False,
) -> None:
    """Append or update a tool step record for later flush to the DB."""
    name = str(evt.get("name") or "tool")
    call_id = str(evt.get("id") or "").strip()
    inp_raw = evt.get("input", {}) or {}
    inp = inp_raw if isinstance(inp_raw, str) else json.dumps(inp_raw)
    if is_start and call_id:
        step = {
            "step_id": call_id,
            "name": name,
            "type": "tool",
            "input": inp,
            "output": "",
            "is_error": False,
            "pending_update": False,
        }
        if "tokens_in" in evt:
            step["tokens_in"] = evt["tokens_in"]
        if "tokens_out" in evt:
            step["tokens_out"] = evt["tokens_out"]
        pending_db_steps.append(step)
        pending_step_ids[call_id] = call_id
        return

    out = str(evt.get("error" if is_error else "output") or "")
    step_data: Dict[str, Any] = {
        "name": name,
        "type": "tool",
        "input": inp,
        "output": out,
        "is_error": is_error,
        "pending_update": False,
    }
    if call_id and call_id in pending_step_ids:
        step_data["step_id"] = call_id
        step_data["pending_update"] = True
    if "tokens_in" in evt:
        step_data["tokens_in"] = evt["tokens_in"]
    if "tokens_out" in evt:
        step_data["tokens_out"] = evt["tokens_out"]

    pending_db_steps.append(step_data)
