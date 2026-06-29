"""Normalize session chart payloads (MCP tools, chart_queue) for chat-ui."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("aion.chart_payload")

# Keep in sync with chat-ui SessionCharts supported kinds.
CHART_KINDS: Set[str] = frozenset({"line", "area", "bar"})


def chart_kind_feature_enabled() -> bool:
    v = (os.getenv("AION_CHART_KIND_ENABLED") or "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def normalize_chart_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure query, data, chart_kind and optional layout keys are safe for Redis/UI.
    Mutates a shallow copy of payload.
    """
    out = dict(payload)
    data = out.get("data")
    if not isinstance(data, list):
        data = []
    out["data"] = data

    if not chart_kind_feature_enabled():
        out["chart_kind"] = "line"
        for k in ("x_key", "series_keys", "stacked", "y_label", "legend_off"):
            out.pop(k, None)
        return out

    kind = out.get("chart_kind")
    if kind is None or str(kind).strip() == "":
        out["chart_kind"] = "line"
    else:
        k = str(kind).strip().lower()
        if k not in CHART_KINDS:
            logger.warning("unknown chart_kind %r, falling back to line", kind)
            out["chart_kind"] = "line"
        else:
            out["chart_kind"] = k

    x_key = out.get("x_key")
    if x_key is not None and str(x_key).strip():
        out["x_key"] = str(x_key).strip()
    else:
        out["x_key"] = "index"

    sk = out.get("series_keys")
    if isinstance(sk, list) and sk:
        out["series_keys"] = [str(s).strip() for s in sk if str(s).strip()]
    else:
        out.pop("series_keys", None)

    stacked = out.get("stacked")
    out["stacked"] = bool(stacked) if stacked is not None else False

    yl = out.get("y_label")
    if yl is not None and str(yl).strip():
        out["y_label"] = str(yl).strip()[:120]
    else:
        out.pop("y_label", None)

    lo = out.get("legend_off")
    out["legend_off"] = bool(lo) if lo is not None else False

    # Light validation: x_key must exist on first row when data present
    if data and isinstance(data[0], dict):
        row0 = data[0]
        xk = out["x_key"]
        if xk not in row0:
            logger.warning("x_key %r missing on chart rows, using index", xk)
            out["x_key"] = "index" if "index" in row0 else next(iter(row0.keys()), "index")

        if out.get("series_keys"):
            keys = set(row0.keys())
            filt = [c for c in out["series_keys"] if c in keys and c != out["x_key"]]
            out["series_keys"] = filt or None
            if not filt:
                out.pop("series_keys", None)

    return out
