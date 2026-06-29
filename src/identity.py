"""Identità utente per path e API (sanitizzazione coerente)."""

from __future__ import annotations

import re
from typing import Optional

_MAX_LEN = 128


def sanitize_user_id(raw: Optional[str], default: str = "default") -> str:
    """
    Riduce user_id a caratteri sicuri per directory e log.
    Se vuoto o None, restituisce default.
    """
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    s = re.sub(r"[^a-zA-Z0-9._@-]", "_", s)
    if len(s) > _MAX_LEN:
        s = s[:_MAX_LEN]
    return s or default
