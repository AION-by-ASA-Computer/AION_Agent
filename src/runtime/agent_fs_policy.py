"""
Agent Filesystem Policy loader.
Caricato da AION_FS_POLICY_PATH (opzionale).
Se il file non esiste, usa i default sicuri (deny exec, allow workspace).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("aion.fs_policy")


class FSPolicy:
    """Policy filesystem per l'agente. Immutabile dopo la creazione."""

    def __init__(self, raw: Dict[str, Any]):
        fs = raw.get("filesystem") or {}
        self.allow_globs: List[str] = list(fs.get("allow", ["workspace/**"]))
        self.deny_globs: List[str] = list(fs.get("deny", []))

        ex = raw.get("exec") or {}
        self.exec_enabled: bool = bool(ex.get("enabled", False))
        self.exec_allowlist: List[Dict[str, Any]] = list(ex.get("allowlist", []))

        lim = raw.get("limits") or {}
        self.max_file_read_bytes: int = int(lim.get("max_file_read_bytes", 2 * 1024 * 1024))
        self.max_file_write_bytes: int = int(lim.get("max_file_write_bytes", 10 * 1024 * 1024))
        self.max_edit_file_bytes: int = int(lim.get("max_edit_file_bytes", 2 * 1024 * 1024))
        self.grep_max_file_bytes: int = int(lim.get("grep_max_file_bytes", 500_000))
        self.grep_max_matches: int = int(lim.get("grep_max_matches", 200))
        self.glob_max_paths: int = int(lim.get("glob_max_paths", 500))
        self.chunk_max_lines: int = int(lim.get("chunk_max_lines", 500))

    @classmethod
    def default(cls) -> FSPolicy:
        return cls({})

    def exec_is_enabled(self) -> bool:
        return self.exec_enabled

    def get_exec_allowlist(self) -> List[Dict[str, Any]]:
        return list(self.exec_allowlist)


@lru_cache(maxsize=1)
def load_fs_policy() -> FSPolicy:
    path_env = (os.environ.get("AION_FS_POLICY_PATH") or "").strip()

    if not path_env:
        logger.info("AION_FS_POLICY_PATH non impostato: uso policy default (exec disabilitato)")
        return FSPolicy.default()

    path = Path(path_env).expanduser().resolve()
    if not path.is_file():
        logger.warning("Policy file non trovato: %s — uso default", path)
        return FSPolicy.default()

    try:
        import yaml

        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        policy = FSPolicy(raw)
        logger.info(
            "Policy caricata da %s: exec_enabled=%s, exec_allowlist=%d entries",
            path,
            policy.exec_enabled,
            len(policy.exec_allowlist),
        )
        return policy
    except Exception as e:
        logger.error("Errore caricamento policy %s: %s — uso default", path, e)
        return FSPolicy.default()


def get_policy() -> FSPolicy:
    return load_fs_policy()
