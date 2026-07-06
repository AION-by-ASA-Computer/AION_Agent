"""
Copy skill package ``scripts/`` trees into a chat session workspace.

Used after ``skill_view`` so ``sandbox_exec_allowlisted`` can run paths like
``scripts/office/unpack.py`` relative to the session root.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..session_workspace import ensure_session_dirs, session_root
from ..skill_registry import skill_registry

logger = logging.getLogger("aion.skill_materialize")

OFFICE_SKILL_SLUGS = frozenset({"docx", "pdf", "xlsx", "pptx"})

# Sentinel paths shown to the agent when materialization succeeds.
_OFFICE_SENTINELS: Dict[str, str] = {
    "docx": "scripts/office/unpack.py",
    "pptx": "scripts/office/unpack.py",
    "xlsx": "scripts/office/soffice.py",
    "pdf": "scripts/check_bounding_boxes.py",
}


@dataclass
class MaterializeResult:
    status: str  # copied | skipped | no_scripts | not_found
    message: str
    sentinel_paths: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "sentinel_paths": self.sentinel_paths,
        }


def _fingerprint_dir(src: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(src.rglob("*")):
        if p.is_file():
            rel = p.relative_to(src).as_posix()
            st = p.stat()
            h.update(rel.encode())
            h.update(str(st.st_size).encode())
            h.update(str(int(st.st_mtime)).encode())
    return h.hexdigest()[:32]


def _marker_path(session_id: str, slug: str) -> Path:
    return session_root(session_id) / ".aion_skill_assets" / f"{slug}.json"


def _load_marker(session_id: str, slug: str) -> Optional[Dict[str, Any]]:
    mp = _marker_path(session_id, slug)
    if not mp.is_file():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_marker(session_id: str, slug: str, payload: Dict[str, Any]) -> None:
    mp = _marker_path(session_id, slug)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(payload, indent=0), encoding="utf-8")


def materialize_skill_scripts(
    session_id: str, slug: str, *, force: bool = False
) -> MaterializeResult:
    """
    Copy ``<skill>/scripts/`` into ``{session}/scripts/`` (merge, idempotent).
    """
    slug = (slug or "").strip()
    if not slug:
        return MaterializeResult("not_found", "Skill slug vuoto.", [])

    if not skill_registry.get_skill_full(slug):
        return MaterializeResult(
            "not_found", f"Skill '{slug}' not found nel registry.", []
        )

    src = skill_registry.get_skill_scripts_dir(slug)
    if not src:
        if slug in OFFICE_SKILL_SLUGS:
            return MaterializeResult(
                "no_scripts",
                f"Skill office '{slug}' senza directory scripts/ sul server "
                "(eseguire sync_config).",
                [],
            )
        return MaterializeResult(
            "no_scripts",
            f"Skill '{slug}' has no scripts/ to materialize.",
            [],
        )

    ensure_session_dirs(session_id)
    dst = session_root(session_id) / "scripts"
    fp = _fingerprint_dir(src)
    prev = _load_marker(session_id, slug)
    if not force and prev and prev.get("fingerprint") == fp:
        sentinels = _sentinel_paths_for_slug(slug, dst)
        return MaterializeResult(
            "skipped",
            f"Scripts already materialized per '{slug}' (unchanged).",
            sentinels,
        )

    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)

    _save_marker(
        session_id,
        slug,
        {
            "slug": slug,
            "fingerprint": fp,
            "source": str(src.resolve()),
        },
    )
    sentinels = _sentinel_paths_for_slug(slug, dst)
    logger.info(
        "materialized skill scripts session=%s slug=%s files~%d",
        session_id[:8],
        slug,
        sum(1 for _ in dst.rglob("*") if _.is_file()),
    )
    return MaterializeResult(
        "copied",
        f"Scripts materialized for '{slug}' in scripts/ (session).",
        sentinels,
    )


def record_skill_viewed(session_id: str, slug: str) -> None:
    """Record that a skill was viewed in this session (even if no scripts materialized)."""
    try:
        mp = _marker_path(session_id, slug)
        if not mp.is_file():
            _save_marker(session_id, slug, {"slug": slug, "viewed_only": True})
    except Exception as e:
        logger.warning("record_skill_viewed failed for %s: %s", slug, e)


def _sentinel_paths_for_slug(slug: str, scripts_dst: Path) -> List[str]:
    """Paths relative to session root that exist after copy."""
    session = scripts_dst.parent
    out: List[str] = []
    preferred = _OFFICE_SENTINELS.get(slug)
    if preferred and (session / preferred).is_file():
        out.append(preferred)
    elif slug in ("docx", "pptx") and (scripts_dst / "office" / "unpack.py").is_file():
        out.append("scripts/office/unpack.py")
    elif slug == "xlsx" and (scripts_dst / "office" / "soffice.py").is_file():
        out.append("scripts/office/soffice.py")
    elif slug == "pdf" and (scripts_dst / "check_bounding_boxes.py").is_file():
        out.append("scripts/check_bounding_boxes.py")
    return out


def format_materialize_footer(result: MaterializeResult, slug: str = "") -> str:
    """Short footer appended to skill_view tool output."""
    if result.status == "not_found":
        return ""
    lines = ["", "---", "**AION skill assets**", result.message]
    if result.sentinel_paths:
        lines.append("Example paths (cwd = session root):")
        for p in result.sentinel_paths[:5]:
            lines.append(f"- `{p}` → `sandbox_exec_allowlisted`")
        if slug and slug in OFFICE_SKILL_SLUGS:
            lines.append(
                "Dopo unpack usa `workspace/unpacked/` come output dir; "
                "leggi XML con `sandbox_read_text_file` / `sandbox_grep_content` (relative_root=workspace)."
            )
    elif result.status == "no_scripts":
        lines.append(
            "No scripts on server: verificare `config_std/skills/<slug>/scripts/` "
        )
    return "\n".join(lines)
