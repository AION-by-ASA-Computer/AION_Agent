import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.memory.ltm_audit")


def append_ltm_audit(
    operation: str,
    payload: Dict[str, Any],
    *,
    admin_user: Optional[str] = None,
    path: str = "data/logs/ltm_audit.jsonl",
) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        rec = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "operation": operation,
            "admin_user": admin_user or "api",
            "payload": payload,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("ltm audit log failed: %s", e)
