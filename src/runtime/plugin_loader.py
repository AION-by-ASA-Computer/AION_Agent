"""Load optional plugins from data/plugins/*.py"""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, List

logger = logging.getLogger("aion.plugins")


class AionAppStub:
    """Minimal surface passed to plugins (hooks, slash, tools)."""

    def __init__(self) -> None:
        from .hooks import hook_registry
        from .slash import slash_router

        self.hooks = hook_registry
        self.slash = slash_router


def load_plugins(app: Any = None) -> List[str]:
    if os.getenv("AION_PLUGINS_ENABLED", "1").lower() not in ("1", "true", "yes"):
        return []
    root = Path(os.getenv("AION_PLUGINS_DIR", "data/plugins"))
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)
        return []
    allow = {
        x.strip()
        for x in (os.getenv("AION_PLUGINS_ALLOWLIST") or "").split(",")
        if x.strip()
    }
    deny = {
        x.strip()
        for x in (os.getenv("AION_PLUGINS_DENYLIST") or "").split(",")
        if x.strip()
    }
    loaded: List[str] = []
    stub = app or AionAppStub()
    for path in sorted(root.glob("*.py")):
        if path.name.startswith("_"):
            continue
        if deny and path.stem in deny:
            continue
        if allow and path.stem not in allow:
            continue
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if not spec or not spec.loader:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            reg = getattr(mod, "register", None)
            if callable(reg):
                reg(stub)
            loaded.append(path.stem)
            logger.info("Loaded plugin %s", path.stem)
        except Exception as e:
            logger.warning("Plugin %s failed: %s", path.name, e)
    return loaded
