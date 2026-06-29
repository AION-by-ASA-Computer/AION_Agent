"""Time-ordered UUIDs for primary keys (UUIDv7)."""
from __future__ import annotations

try:
    from uuid import uuid7 as _uuid7_impl  # Python 3.14+
except ImportError:
    from uuid6 import uuid7 as _uuid7_impl  # type: ignore[import-not-found,unused-ignore]


def new_uuid7_str() -> str:
    """Return canonical string form of a UUIDv7 (sortable by time)."""
    return str(_uuid7_impl())
