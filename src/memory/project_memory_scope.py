"""Shared project ↔ MemPalace wing/room conventions (aligned with SQL QueryMemory slugs)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from src.session_workspace import data_root

# Stable navigation rooms inside each project wing (MemPalace entity-first wings).
NAV_ROOMS = frozenset(
    {
        "entry_points",
        "join_paths",
        "pitfalls",
        "heuristics",
        "limitations",
        "discoveries",
    }
)

# Public alias used by navigation-memory API and chat-ui.
NAVIGATION_ROOMS = NAV_ROOMS

DEFAULT_NAV_ROOM = "discoveries"

_DATA_TURN_HINTS = (
    "sql",
    "select",
    "table",
    "schema",
    "join",
    "query",
    "database",
    "mysql",
    "postgres",
    "column",
    "mempalace",
    "memory",
    "data",
    "report",
    "count",
    "asset",
    "warehouse",
    "metadata",
    "openmetadata",
    "drawer",
    "navig",
)


def should_inject_project_context(
    user_input: str,
    *,
    project_slug: Optional[str] = None,
) -> bool:
    """Inject project scope when a non-default SQL project is active, else gate chitchat."""
    slug = sanitize_project_slug(project_slug or "default")
    if slug != "default":
        return True
    q = (user_input or "").strip().lower()
    if not q:
        return False
    if any(h in q for h in _DATA_TURN_HINTS):
        return True
    return len(q) > 120


_KG_PREDICATES = frozenset(
    {
        "joins_via",
        "entry_for",
        "avoids_join",
        "requires_filter",
        "deprecated",
        "links_to",
    }
)

_WING_ROOM_RE = re.compile(r"^[a-z0-9_\-]+$")


def sanitize_id(part: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]", "_", (part or "default").lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80] or "default"


def sanitize_project_slug(project_slug: str) -> str:
    """Normalize SQL QueryMemory / MemPalace project slug."""
    return sanitize_id(project_slug)


def project_wing_prefix() -> str:
    return (os.getenv("AION_MEMPALACE_PROJECT_WING_PREFIX") or "wing_proj_").strip()


def project_wing(project_slug: str) -> str:
    """MemPalace wing for a SQL QueryMemory project slug."""
    slug = sanitize_id(project_slug or "default")
    prefix = project_wing_prefix()
    if not prefix.endswith("_") and prefix:
        prefix = prefix.rstrip("_") + "_"
    wing = f"{prefix}{slug}" if prefix else f"wing_proj_{slug}"
    return wing[:120]


def user_wing(user_id: str) -> str:
    return f"wing_user_{sanitize_id(user_id)}"


def is_valid_wing_room(name: str) -> bool:
    return bool(name and _WING_ROOM_RE.match(name))


def normalize_nav_room(room: Optional[str]) -> str:
    r = (room or "").strip().lower()
    if r in NAV_ROOMS:
        return r
    return DEFAULT_NAV_ROOM


def room_hints_from_query(query: str) -> List[str]:
    """Optional room filter hints from user text (Italian + English keywords)."""
    q = (query or "").lower()
    hints: List[str] = []
    if any(w in q for w in ("join", "colleg", "relaz", "foreign", "fk")):
        hints.append("join_paths")
    if any(w in q for w in ("sscc", "cliente", "ordini", "entry", "partire", "inizi")):
        hints.append("entry_points")
    if any(
        w in q
        for w in ("errore", "fallit", "0 righe", "timeout", "pitfall", "non funz")
    ):
        hints.append("pitfalls")
    if any(w in q for w in ("trim", "cast", "euristic", "heuristic", "filtro")):
        hints.append("heuristics")
    if any(w in q for w in ("limite", "read-only", "solo lettura", "enorme", "lento")):
        hints.append("limitations")
    return hints


def mempalace_nav_enabled() -> bool:
    return os.getenv("AION_MEMPALACE_NAV_ENABLED", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def nav_pre_turn_inject_enabled() -> bool:
    """Pre-turn MemPalace nav inject is opt-in (default off — agent calls mempalace_search)."""
    return os.getenv("AION_MEMPALACE_NAV_PRE_TURN_INJECT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mempalace_nav_auto_learn_enabled() -> bool:
    return os.getenv("AION_MEMPALACE_NAV_AUTO_LEARN", "0").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def nav_inject_threshold() -> float:
    try:
        return float(os.getenv("AION_MEMPALACE_NAV_INJECT_THRESHOLD", "0.75"))
    except ValueError:
        return 0.75


def nav_search_limit() -> int:
    try:
        return max(1, min(20, int(os.getenv("AION_MEMPALACE_NAV_SEARCH_LIMIT", "5"))))
    except ValueError:
        return 5


def duplicate_check_threshold() -> float:
    try:
        return float(os.getenv("AION_MEMPALACE_DEDUP_THRESHOLD", "0.87"))
    except ValueError:
        return 0.87


def mempalace_nav_auto_kg_enabled() -> bool:
    return os.getenv("AION_MEMPALACE_NAV_AUTO_KG", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mempalace_palace_directory(tenant_id: str) -> Path:
    """
    Per-tenant MemPalace data directory (Chroma + KG SQLite).
    Override with ``AION_MEMPALACE_PALACE_PATH`` (absolute path to palace root).
    """
    explicit = (os.getenv("AION_MEMPALACE_PALACE_PATH") or "").strip()
    tid = sanitize_id(tenant_id or "default")
    if explicit:
        base = Path(explicit)
        if not base.is_absolute():
            base = data_root() / base
        path = base / tid if base.name != tid else base
    else:
        path = data_root() / "mempalace" / tid
    path.mkdir(parents=True, exist_ok=True)
    return path


def apply_mempalace_palace_env(env: dict, tenant_id: str) -> None:
    """Set ``MEMPALACE_PALACE_PATH`` on MCP subprocess env when not already set."""
    if env.get("MEMPALACE_PALACE_PATH"):
        return
    env["MEMPALACE_PALACE_PATH"] = str(mempalace_palace_directory(tenant_id))


def resolve_project_slug(
    explicit: Optional[str] = None,
    *,
    default: str = "default",
) -> str:
    slug = (explicit or os.getenv("AION_SQL_QM_DEFAULT_PROJECT") or default).strip()
    return slug or default


def project_scope_hint_from_meta(
    project_slug: str,
    *,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Scope line for prompts — driven by SQL QueryMemory project metadata (UI/admin),
    not hardcoded slugs.
    """
    slug = sanitize_id(project_slug or "default")
    desc = (description or "").strip()
    if desc:
        return f"scope ({slug}): {desc}"
    name = (display_name or "").strip()
    if name:
        return (
            f"scope ({slug}): SQL QueryMemory and MemPalace navigation for {name!r}. "
            "Persist only queries and drawers relevant to this project."
        )
    return (
        f"scope ({slug}): use this project wing ({project_wing(slug)}) and QueryMemory bucket only. "
        "Set a project description in admin to narrow scope."
    )


async def project_context_block_async(
    project_slug: str,
    *,
    tenant_id: Optional[str] = None,
    profile_slug: Optional[str] = None,
) -> str:
    """Build LTM/nav context block with scope loaded from ``sql_query_projects``."""
    from .sql_query_memory import sql_query_memory
    from .sql_query_memory.scope import default_tenant_id

    slug = sanitize_project_slug(project_slug)
    tid = tenant_id or default_tenant_id()
    row = await sql_query_memory.get_project_by_slug(slug, tenant_id=tid)
    return project_context_block(
        slug,
        profile_slug,
        display_name=row.display_name if row else None,
        description=row.description if row else None,
    )


def project_context_block(
    project_slug: str,
    profile_slug: Optional[str] = None,
    *,
    display_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    slug = sanitize_project_slug(project_slug)
    wing = project_wing(slug)
    lines = [
        f"project: {slug}",
        f"wing: {wing}",
        project_scope_hint_from_meta(
            slug, display_name=display_name, description=description
        ),
    ]
    if profile_slug:
        lines.append(f"profile: {profile_slug}")
    return "[project_context]\n" + "\n".join(lines)
