from __future__ import annotations

import uuid


def new_run_id(prefix: str = "bench") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"
