"""Stable IDs for tool_start / tool_end correlation (SSE + chat-ui)."""
from __future__ import annotations

import uuid


def new_tool_call_id() -> str:
    return "tc_" + uuid.uuid4().hex[:12]
