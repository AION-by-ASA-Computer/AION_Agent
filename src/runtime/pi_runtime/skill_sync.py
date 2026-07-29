"""Sync AION profile skills to Pi Agent Skills layout."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List

logger = logging.getLogger("aion.pi_skill_sync")

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _skill_slug(name: str) -> str:
    slug = _SAFE.sub("_", (name or "skill").strip().lower()).strip("_")
    return slug or "skill"


def sync_profile_skills(session_id: str, profile: Any) -> List[str]:
    """Write profile skills under ``<session>/.pi/skills/<name>/SKILL.md``."""
    from src.runtime.long_run_mode import pi_session_dir
    from src.skill_registry import SkillRegistry

    agent_dir = Path(pi_session_dir(session_id))
    skills_root = agent_dir / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    registry = SkillRegistry()
    wanted = set(profile.skills or [])
    summaries = registry.list_summaries(
        allowed_names=list(wanted) if wanted else None,
    )
    written: List[str] = []

    for meta in summaries:
        name = str(meta.get("name") or "")
        if not name:
            continue
        desc = str(meta.get("description") or name)
        body = registry.get_skill(name) or ""
        skill_dir = skills_root / _skill_slug(name)
        skill_dir.mkdir(parents=True, exist_ok=True)
        content = f"---\nname: {name}\ndescription: {desc}\n---\n\n{body.strip()}\n"
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        written.append(name)

    logger.info(
        "pi_skill_sync session=%s skills=%d",
        session_id[:8],
        len(written),
    )
    return written
