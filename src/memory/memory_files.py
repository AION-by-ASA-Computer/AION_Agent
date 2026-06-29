"""File bounded SOUL/MEMORY/USER per profilo (Hermes FASE G)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from ..identity import sanitize_user_id


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _profile_state_root() -> Path:
    return _project_root() / Path(os.getenv("AION_PROFILE_STATE_DIR", "data/profiles"))


def soul_read_path(profile_slug: str) -> Optional[Path]:
    """
    Primo file SOUL.md esistente: `config/profiles/<slug>/SOUL.md` se la cartella profilo esiste,
    altrimenti `data/profiles/<slug>/SOUL.md` (profili flat `.yaml`).
    """
    root = _project_root()
    cfg = root / "config" / "profiles"
    meta_dir = cfg / profile_slug
    candidates = []
    if meta_dir.is_dir():
        candidates.append(meta_dir / "SOUL.md")
    candidates.append(_profile_state_root() / profile_slug / "SOUL.md")
    for p in candidates:
        if p.is_file():
            return p
    return None


def soul_write_path(profile_slug: str) -> Path:
    """Percorso dove creare/aggiornare SOUL (cartella config se esiste, altrimenti data/profiles)."""
    root = _project_root()
    cfg = root / "config" / "profiles"
    meta_dir = cfg / profile_slug
    if meta_dir.is_dir():
        return meta_dir / "SOUL.md"
    p = _profile_state_root() / profile_slug / "SOUL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


class BoundedMemoryFile:
    def __init__(self, path: Path, max_chars: int):
        self.path = path
        self.max_chars = max_chars
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> str:
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def write(self, content: str) -> None:
        if len(content) > self.max_chars:
            raise ValueError(f"Content exceeds limit: {len(content)}/{self.max_chars}")
        self.path.write_text(content, encoding="utf-8")

    def add_entry(self, entry: str, separator: str = "\n---\n") -> Dict[str, Any]:
        current = self.read()
        new_content = (current + separator + entry) if current else entry
        if len(new_content) > self.max_chars:
            return {
                "success": False,
                "error": (
                    f"Memory at {len(current)}/{self.max_chars} chars. "
                    "Consolidare o rimuovere prima di aggiungere."
                ),
                "usage": f"{len(current)}/{self.max_chars}",
            }
        self.write(new_content)
        return {"success": True, "usage": f"{len(new_content)}/{self.max_chars}"}

    def replace(self, new_content: str) -> Dict[str, Any]:
        try:
            self.write(new_content)
            return {"success": True, "usage": f"{len(new_content)}/{self.max_chars}"}
        except ValueError as e:
            return {"success": False, "error": str(e)}

    def usage_pct(self) -> float:
        return len(self.read()) / self.max_chars if self.max_chars else 0.0


class ProfileMemoryBundle:
    """Snapshot SOUL (config o data/profiles) + MEMORY/USER (data/profiles)."""

    def __init__(self, profile_slug: str, user_id: str):
        uid = sanitize_user_id(user_id)
        root = Path(__file__).resolve().parents[2]
        sp = soul_read_path(profile_slug)
        self.soul_path = sp

        data_root = Path(os.getenv("AION_PROFILE_STATE_DIR", "data/profiles"))
        root_data = root / data_root / profile_slug
        self.memory = BoundedMemoryFile(
            root_data / "MEMORY.md",
            max_chars=int(os.getenv("AION_MEMORY_FILE_MAX_CHARS", "2200")),
        )
        self.user = BoundedMemoryFile(
            root_data / uid / "USER.md",
            max_chars=int(os.getenv("AION_USER_FILE_MAX_CHARS", "1400")),
        )

    def snapshot(self) -> Dict[str, str]:
        soul = ""
        if self.soul_path and self.soul_path.exists():
            soul = self.soul_path.read_text(encoding="utf-8")
        return {
            "soul": soul,
            "memory": self.memory.read(),
            "user": self.user.read(),
        }


def soul_bounded_file(profile_slug: str) -> BoundedMemoryFile:
    path = soul_write_path(profile_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    max_chars = int(os.getenv("AION_SOUL_FILE_MAX_CHARS", "12000"))
    return BoundedMemoryFile(path, max_chars)


def profile_operative_memory_file(profile_slug: str) -> BoundedMemoryFile:
    """MEMORY.md condiviso per profilo (indipendente da user_id)."""
    p = _profile_state_root() / profile_slug / "MEMORY.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    return BoundedMemoryFile(
        p, max_chars=int(os.getenv("AION_MEMORY_FILE_MAX_CHARS", "2200"))
    )
