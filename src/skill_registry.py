"""Registry skill Markdown con frontmatter, curated + generated (Hermes FASE A)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

logger = logging.getLogger("aion.skills")


class SkillRegistry:
    """Carica skill da config/skills e da data/skills/generated con merge per versione."""

    def __init__(
        self,
        curated_dir: str = "config/skills",
        curated_fallback_dir: str = "config_std/skills",
        generated_dir: Optional[str] = None,
    ):
        self._root = Path(__file__).resolve().parent.parent
        self.curated_dir = self._root / curated_dir
        self.curated_fallback_dir = self._root / curated_fallback_dir
        gen = generated_dir or os.getenv(
            "AION_SKILL_GENERATED_DIR", "data/skills/generated"
        )
        self.generated_dir = self._root / gen
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._dir_mtime: float = 0.0
        self.load_all()

    def _compute_dirs_mtime(self) -> float:
        mtimes: List[float] = []
        for d in (self.curated_fallback_dir, self.curated_dir, self.generated_dir):
            if not d.exists():
                continue
            try:
                mtimes.append(d.stat().st_mtime)
            except OSError:
                pass
            for f in d.rglob("*.md"):
                try:
                    mtimes.append(f.stat().st_mtime)
                except OSError:
                    pass
        return max(mtimes) if mtimes else 0.0

    def reload_if_stale(self, *, force: bool = False) -> None:
        current = self._compute_dirs_mtime()
        if force or current != self._dir_mtime:
            self.load_all()
            self._dir_mtime = current

    def load_all(self) -> None:
        self._skills.clear()
        # Load curated fallback first, then local curated overrides.
        self._load_dir(self.curated_fallback_dir, source="curated")
        self._load_dir(self.curated_dir, source="curated")
        if self.generated_dir.exists():
            self._load_dir(self.generated_dir, source="generated")

    def _default_meta(self, stem: str) -> Dict[str, Any]:
        return {
            "name": stem,
            "description": stem.replace("_", " ").title(),
            "tags": [],
            "status": "verified",
            "source": "curated",
            "version": 1,
            "parent": None,
        }

    def _load_dir(self, d: Path, source: str) -> None:
        if not d.exists():
            return
        # Supporto per Skill Packages: cartelle con SKILL.md o file .md singoli
        for f in sorted(d.rglob("*.md")):
            # Se è in una sottocartella, deve chiamarsi SKILL.md o skill.md per essere la radice
            if f.parent != d and f.name.lower() not in ["skill.md", "index.md"]:
                continue

            try:
                post = frontmatter.loads(f.read_text(encoding="utf-8"))
                meta_raw = dict(post.metadata) if post.metadata else {}
                body = post.content or ""
                slug = meta_raw.get("name") or f.stem
                version = int(meta_raw.get("version", 1))
                base = self._default_meta(slug)
                base.update(
                    {
                        "name": slug,
                        "description": meta_raw.get("description", base["description"]),
                        "tags": meta_raw.get("tags") or [],
                        "status": meta_raw.get("status", "verified"),
                        "source": source,
                        "version": version,
                        "parent": meta_raw.get("parent"),
                    }
                )
                existing = self._skills.get(slug)
                if existing and int(existing["meta"].get("version", 1)) > version:
                    continue
                self._skills[slug] = {"meta": base, "body": body, "path": str(f)}
            except Exception as e:
                logger.error("Skill load failed %s: %s", f, e)
        self._dir_mtime = self._compute_dirs_mtime()

    def skill_exists(self, name: str) -> bool:
        return name in self._skills

    def reload(self) -> None:
        self.load_all()

    def list_summaries(
        self,
        allowed_names: Optional[List[str]] = None,
        *,
        include_draft: bool = False,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for name, s in self._skills.items():
            meta = s["meta"]
            if not include_draft and meta.get("status") == "draft":
                continue
            if allowed_names is not None and name not in allowed_names:
                continue
            out.append(dict(meta))
        return out

    def get_skill_full(self, name: str) -> Optional[str]:
        s = self._skills.get(name)
        return s["body"] if s else None

    def get_skill(self, name: str) -> Optional[str]:
        """Alias retro-compatibile → body completo."""
        return self.get_skill_full(name)

    def get_meta(self, name: str) -> Optional[Dict[str, Any]]:
        s = self._skills.get(name)
        return dict(s["meta"]) if s else None

    def get_skill_path(self, name: str) -> Optional[Path]:
        """Filesystem path of the loaded skill markdown file."""
        s = self._skills.get(name)
        if not s:
            return None
        p = Path(s["path"])
        return p if p.is_file() else None

    def get_skill_package_root(self, name: str) -> Optional[Path]:
        """Directory root for a skill package (folder containing SKILL.md)."""
        p = self.get_skill_path(name)
        if not p:
            return None
        if p.name.lower() in ("skill.md", "index.md"):
            return p.parent
        return p.parent

    def get_skill_scripts_dir(self, name: str) -> Optional[Path]:
        """``<package>/scripts`` when present on disk.

        If the loaded skill path is a thin override under ``config/skills/`` (e.g. only
        an older ``SKILL.md``), fall back to ``config_std/skills/<name>/scripts``.
        """
        root = self.get_skill_package_root(name)
        if root:
            scripts = root / "scripts"
            if scripts.is_dir():
                return scripts
        fallback_pkg = self.curated_fallback_dir / name
        fb_scripts = fallback_pkg / "scripts"
        if fb_scripts.is_dir():
            return fb_scripts
        return None

    def get_all_names(self) -> List[str]:
        return list(self._skills.keys())

    def delete_skill(self, name: str) -> bool:
        s = self._skills.get(name)
        if not s:
            return False
        path = Path(s["path"])
        if path.exists():
            path.unlink()
        self.load_all()
        return True

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        allowed_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        q = (query or "").lower()
        scored: List[tuple] = []
        for name, s in self._skills.items():
            if allowed_names is not None and name not in allowed_names:
                continue
            meta = s["meta"]
            if meta.get("status") == "draft":
                continue
            score = 0
            if q in name.lower():
                score += 3
            desc = (meta.get("description") or "").lower()
            if q in desc:
                score += 2
            for t in meta.get("tags") or []:
                if q in str(t).lower():
                    score += 1
            if score > 0:
                scored.append((score, dict(meta)))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]


skill_registry = SkillRegistry()
