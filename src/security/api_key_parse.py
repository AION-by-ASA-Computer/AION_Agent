"""Pure API key header parsing (stdlib only; safe for fuzz harness imports)."""

from __future__ import annotations


def parse_api_key(header_val: str | None) -> tuple[str | None, str | None]:
    if not header_val or not header_val.startswith("aion_"):
        return None, None
    parts = header_val.split("_", 2)
    if len(parts) < 3:
        return None, None
    prefix, secret = parts[1], parts[2]
    if len(prefix) < 4 or len(secret) < 8:
        return None, None
    return prefix, secret
