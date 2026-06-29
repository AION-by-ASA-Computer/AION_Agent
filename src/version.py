"""Centralized version utility loading from root version.json"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("aion.version")

_ROOT = Path(__file__).resolve().parent.parent


def get_version() -> str:
    version_file = _ROOT / "version.json"
    if version_file.exists():
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                v = data.get("version")
                if v:
                    return v
        except Exception as e:
            logger.warning("Failed to parse version.json at %s: %s", version_file, e)
    return "v1.0.0"


__version__ = get_version()
