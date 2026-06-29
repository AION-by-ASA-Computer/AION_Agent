"""Validate cron expressions and compute next run (croniter + timezone)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from croniter import croniter


def default_timezone() -> str:
    return (os.environ.get("AION_CRON_DEFAULT_TIMEZONE") or "UTC").strip() or "UTC"


def validate_cron_expression(expr: str, tz_name: Optional[str] = None) -> str:
    """Return normalized cron expression or raise ValueError."""
    s = (expr or "").strip()
    if not s:
        raise ValueError("cron_expression is required")
    tz = (tz_name or default_timezone()).strip() or "UTC"
    try:
        ZoneInfo(tz)
    except Exception as e:
        raise ValueError(f"Invalid timezone: {tz}") from e
    try:
        base = datetime.now(ZoneInfo(tz))
        it = croniter(s, base)
        _ = it.get_next(datetime)
    except Exception as e:
        raise ValueError(f"Invalid cron expression: {s!r}") from e
    return s


def compute_next_run_at(
    expr: str,
    tz_name: Optional[str] = None,
    *,
    after: Optional[datetime] = None,
) -> datetime:
    """Next fire time as UTC-aware datetime."""
    s = validate_cron_expression(expr, tz_name)
    tz = (tz_name or default_timezone()).strip() or "UTC"
    zi = ZoneInfo(tz)
    base = after or datetime.now(zi)
    if base.tzinfo is None:
        base = base.replace(tzinfo=zi)
    else:
        base = base.astimezone(zi)
    nxt = croniter(s, base).get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=zi)
    return nxt.astimezone(timezone.utc)


def validate_session_mode(mode: str) -> str:
    m = (mode or "fixed").strip().lower()
    if m not in ("fixed", "new"):
        raise ValueError("session_mode must be 'fixed' or 'new'")
    return m
