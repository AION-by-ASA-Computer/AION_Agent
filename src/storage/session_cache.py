"""Local cache for object-storage files so MCP sandbox can read from disk."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Set

from src.session_workspace import data_root
from src.storage import get_storage_backend


class SessionFileCache:
    def __init__(self) -> None:
        self._backend = get_storage_backend()

    def _conv_dir(self, conversation_id: str) -> Path:
        return data_root() / "sessions" / conversation_id

    def ensure_local(self, conversation_id: str, storage_key: str) -> Path:
        """Download object to uploads cache if missing; return local path."""
        uploads = self._conv_dir(conversation_id) / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        name = storage_key.rsplit("/", 1)[-1]
        dest = uploads / name
        if dest.is_file():
            return dest
        lockf = uploads / f".{name}.lock"
        lockf.parent.mkdir(parents=True, exist_ok=True)
        with open(lockf, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                if not dest.is_file():
                    body = self._backend.get_object(storage_key)
                    dest.write_bytes(body)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
        return dest

    def promote_to_storage(self, conversation_id: str, local_path: Path, kind: str = "output") -> str:
        tenant = os.getenv("AION_DEFAULT_TENANT_ID", "default")
        key = f"{tenant}/conversations/{conversation_id}/{kind}s/{local_path.name}"
        data = local_path.read_bytes()
        mime = "application/octet-stream"
        self._backend.put_object(key, data, mime)
        return key

    def snapshot_workspace(self, conversation_id: str) -> Set[str]:
        ws = self._conv_dir(conversation_id) / "workspace"
        if not ws.is_dir():
            return set()
        return {p.name for p in ws.iterdir() if p.is_file()}

    def diff_workspace(self, conversation_id: str, baseline: Set[str]) -> list[Path]:
        ws = self._conv_dir(conversation_id) / "workspace"
        if not ws.is_dir():
            return []
        out: list[Path] = []
        for p in ws.iterdir():
            if p.is_file() and p.name not in baseline and not p.name.startswith("."):
                if p.name in ("_sandbox_last_run.py",):
                    continue
                out.append(p)
        return out


session_file_cache = SessionFileCache()
