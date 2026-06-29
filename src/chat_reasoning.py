"""Streaming helpers for reasoning chunks."""
from __future__ import annotations

import json
from typing import Any


def coerce_reasoning_piece(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)
