"""Entity mention index for Mnemos recall (not a graph)."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from sqlalchemy import text

from src.data.engine import get_async_session_maker
from src.memory.mnemos.types import MemoryScope

logger = logging.getLogger("aion.memory.mnemos.entities")

_BUILTIN_ALIASES: Dict[str, List[str]] = {
    "k8s": ["kubernetes", "kube"],
    "pg": ["postgresql", "postgres"],
    "mfa": ["multi-factor authentication", "multi factor authentication", "2fa"],
    "sla": ["service level agreement"],
    "ci": ["continuous integration"],
}


def entity_recall_enabled() -> bool:
    return os.getenv("AION_MNEMOS_ENTITY_RECALL", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


async def upsert_entity(
    scope: MemoryScope,
    *,
    canonical_key: str,
    display_name: str,
    kind: str = "generic",
    aliases: Optional[List[str]] = None,
) -> int:
    key = _normalize_key(canonical_key)
    alias_json = json.dumps(sorted(set(aliases or [])))
    now = datetime.now(timezone.utc)
    async with get_async_session_maker()() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT id FROM ltm_entities
                    WHERE tenant_id = :tid AND scope_type = :st AND scope_key = :sk
                      AND canonical_key = :ck
                    """
                ),
                {
                    "tid": scope.tenant_id,
                    "st": scope.scope_type,
                    "sk": scope.scope_key,
                    "ck": key,
                },
            )
        ).first()
        if row:
            eid = int(row[0])
            await session.execute(
                text(
                    """
                    UPDATE ltm_entities
                    SET display_name = :dn, aliases_json = :aj, last_seen = :now,
                        mention_count = mention_count + 1
                    WHERE id = :id
                    """
                ),
                {"dn": display_name, "aj": alias_json, "now": now, "id": eid},
            )
        else:
            res = await session.execute(
                text(
                    """
                    INSERT INTO ltm_entities
                    (tenant_id, scope_type, scope_key, kind, canonical_key,
                     display_name, aliases_json, first_seen, last_seen, mention_count)
                    VALUES (:tid, :st, :sk, :kind, :ck, :dn, :aj, :now, :now, 1)
                    """
                ),
                {
                    "tid": scope.tenant_id,
                    "st": scope.scope_type,
                    "sk": scope.scope_key,
                    "kind": kind,
                    "ck": key,
                    "dn": display_name,
                    "aj": alias_json,
                    "now": now,
                },
            )
            eid = int(res.lastrowid)
        await session.commit()
        return eid


async def link_note_entity(note_id: int, entity_id: int) -> None:
    async with get_async_session_maker()() as session:
        await session.execute(
            text(
                "INSERT OR IGNORE INTO ltm_note_entities (note_id, entity_id) "
                "VALUES (:nid, :eid)"
            ),
            {"nid": note_id, "eid": entity_id},
        )
        await session.commit()


async def seed_builtin_aliases(scope: MemoryScope) -> int:
    seeded = 0
    for alias, expansions in _BUILTIN_ALIASES.items():
        await upsert_entity(
            scope,
            canonical_key=alias,
            display_name=alias.upper(),
            kind="abbreviation",
            aliases=expansions,
        )
        seeded += 1
    return seeded


async def seed_project_aliases(tenant_id: str = "default") -> int:
    """Seed entity aliases from authoritative project records."""
    try:
        from src.memory.sql_query_memory import sql_query_memory
    except Exception:
        return 0
    count = 0
    try:
        projects = await sql_query_memory.list_projects(tenant_id=tenant_id)
    except Exception as exc:
        logger.debug("project alias seed skipped: %s", exc)
        return 0
    for proj in projects or []:
        slug = str(getattr(proj, "slug", None) or proj.get("slug") or "")
        if not slug:
            continue
        scope = MemoryScope(tenant_id, "project", slug)
        await upsert_entity(
            scope,
            canonical_key=slug,
            display_name=slug,
            kind="project",
            aliases=[slug.replace("-", " "), slug.replace("_", " ")],
        )
        count += 1
    return count


async def search_entity_note_ids(
    scope: MemoryScope,
    query: str,
    *,
    limit: int = 20,
) -> List[int]:
    """Resolve query tokens against entity aliases; return linked note ids."""
    if not entity_recall_enabled():
        return []
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    if not tokens:
        return []
    tid, st, sk = scope.as_tuple()
    async with get_async_session_maker()() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, canonical_key, display_name, aliases_json
                    FROM ltm_entities
                    WHERE tenant_id = :tid AND scope_type = :st AND scope_key = :sk
                    """
                ),
                {"tid": tid, "st": st, "sk": sk},
            )
        ).all()
    matched_entity_ids: Set[int] = set()
    for eid, canonical, display, aliases_json in rows:
        hay = {canonical, _normalize_key(display or "")}
        try:
            hay |= {_normalize_key(a) for a in json.loads(aliases_json or "[]")}
        except json.JSONDecodeError:
            pass
        hay |= set(re.findall(r"[a-z0-9]+", (display or "").lower()))
        if tokens & hay:
            matched_entity_ids.add(int(eid))
    if not matched_entity_ids:
        return []
    eid_list = ",".join(str(i) for i in matched_entity_ids)
    async with get_async_session_maker()() as session:
        res = await session.execute(
            text(
                f"""
                SELECT note_id FROM ltm_note_entities
                WHERE entity_id IN ({eid_list})
                LIMIT {int(limit)}
                """
            )
        )
        return [int(r[0]) for r in res.all()]


async def split_entity(entity_id: int, *, new_canonical_key: str) -> int:
    """Split a wrongly merged entity (audit-friendly corrective action)."""
    async with get_async_session_maker()() as session:
        row = (
            await session.execute(
                text("SELECT tenant_id, scope_type, scope_key, display_name FROM ltm_entities WHERE id = :id"),
                {"id": entity_id},
            )
        ).first()
        if not row:
            raise ValueError("entity_not_found")
        scope = MemoryScope(row[0], row[1], row[2])
    return await upsert_entity(
        scope,
        canonical_key=new_canonical_key,
        display_name=new_canonical_key,
        kind="split",
    )
