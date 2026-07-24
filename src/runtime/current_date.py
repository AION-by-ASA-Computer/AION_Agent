"""Shared utility: ground LLMs in the real current date each turn.

Without an explicit date preamble, models fall back to their training-cutoff
year and emit stale answers (e.g. assuming the 2022 FIFA World Cup when today
is 2026).  Centralised here so every consumer (deep-research, augment, etc.)
stays in sync.
"""

from __future__ import annotations

from datetime import datetime


def current_date_context() -> str:
    """Return a short preamble that tells the LLM today's real date.

    System-TZ-local so the date matches what the user sees.
    Uses only portable strftime directives (no %-d etc.).
    """
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%B %d, %Y')} ({now.strftime('%Y-%m-%d')}). "
        f"When a query needs a year or refers to 'latest'/'current'/'this year', "
        f"use {now.strftime('%Y')} or relative wording — never a year inferred "
        f"from training data.\n\n"
    )
