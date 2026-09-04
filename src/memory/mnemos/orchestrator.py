"""Mnemos orchestrator facade for pipeline integration."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.skill_registry import skill_registry

from .compress import schedule_compress
from .format import format_wake_block
from .recall import recall, recall_across_scopes
from .scope import (
    parse_scope_name,
    resolve_scope_for_write,
    resolve_scopes_for_wake,
)
from . import store
from .wake import wake, wake_budget

logger = logging.getLogger("aion.memory.mnemos.orchestrator")

_LTM_MIN_IMPORTANCE = int(os.getenv("AION_LTM_MIN_IMPORTANCE", "2"))


def _parse_confidence(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 1.0


def _parse_valid_from(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class MnemosOrchestrator:
    async def wake_up(
        self,
        *,
        tenant_id: str,
        user_id: str,
        active_project_slug: Optional[str] = None,
        include_global: bool = False,
    ) -> str:
        scopes = resolve_scopes_for_wake(
            tenant_id=tenant_id,
            user_id=user_id,
            active_project_slug=active_project_slug,
            include_global=include_global,
        )
        blocks: List[str] = []
        for scope in scopes:
            rows = await wake(scope, wake_budget())
            if not rows:
                continue
            header = f"## Mnemos wake ({scope.scope_type}:{scope.scope_key})"
            blocks.append(format_wake_block(rows, header=header))
        return "\n\n".join(blocks)

    async def add_note(
        self,
        *,
        tenant_id: str,
        user_id: str,
        text: str,
        scope_name: str = "user",
        category: str = "fact",
        importance: int = 3,
        active_project_slug: Optional[str] = None,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        supersede_hint: Optional[str] = None,
        confidence: float = 1.0,
        confidence_source: Optional[str] = None,
        valid_from: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        scope = resolve_scope_for_write(
            tenant_id=tenant_id,
            user_id=user_id,
            scope_name=scope_name,
            active_project_slug=active_project_slug,
        )
        note = await store.insert_note(
            scope,
            content=text,
            category=category,
            importance=importance,
            source_session_id=source_session_id,
            source_message_id=source_message_id,
            confidence=confidence,
            confidence_source=confidence_source,
            valid_from=valid_from or datetime.now(timezone.utc),
        )
        if supersede_hint:
            candidates = await store.find_supersede_candidates(
                scope, supersede_hint, limit=3
            )
            for c in candidates:
                if c.id != note.id:
                    await store.supersede_note(c.id, note)
        schedule_compress(scope, seq=note.seq)
        return {
            "id": note.id,
            "seq": note.seq,
            "scope_type": scope.scope_type,
            "scope_key": scope.scope_key,
            "content": note.content,
        }

    async def recall_notes(
        self,
        *,
        tenant_id: str,
        user_id: str,
        query: str,
        scope_name: str = "auto",
        mode: str = "current",
        active_project_slug: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        parsed = (scope_name or "auto").strip().lower()
        if parsed in ("auto", "all"):
            scopes = resolve_scopes_for_wake(
                tenant_id=tenant_id,
                user_id=user_id,
                active_project_slug=active_project_slug,
                include_global=os.getenv("AION_MNEMOS_WAKE_GLOBAL", "0").lower()
                in ("1", "true", "yes"),
            )
            return await recall_across_scopes(scopes, query, limit=limit, mode=mode)
        scope = resolve_scope_for_write(
            tenant_id=tenant_id,
            user_id=user_id,
            scope_name=parsed,
            active_project_slug=active_project_slug,
        )
        return await recall(scope, query, limit=limit, mode=mode)

    async def forget(self, note_id: int, *, hard: bool = False) -> bool:
        return await store.forget_note(note_id, hard=hard)

    def _extraction_skill_text(self) -> str:
        return skill_registry.get_skill("ltm_note_extraction") or ""

    async def apply_extraction(
        self,
        data: Dict[str, Any],
        *,
        tenant_id: str,
        user_id: str,
        active_project_slug: Optional[str] = None,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
    ) -> int:
        if not data.get("should_persist"):
            return 0
        notes = data.get("notes") or []
        saved = 0
        for raw in notes:
            if not isinstance(raw, dict):
                continue
            text = (raw.get("text") or raw.get("content") or "").strip()
            if len(text) < 3:
                continue
            try:
                imp = int(raw.get("importance", 3))
            except (TypeError, ValueError):
                imp = 3
            if imp < _LTM_MIN_IMPORTANCE:
                continue
            scope_name = parse_scope_name(str(raw.get("scope") or "user"))
            if scope_name == "project" and not active_project_slug:
                scope_name = "user"
            conf = _parse_confidence(raw.get("confidence", 1.0))
            conf_src = str(raw.get("confidence_source") or "extraction")[:24]
            valid_from = _parse_valid_from(raw.get("valid_from"))
            try:
                await self.add_note(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    text=text,
                    scope_name=scope_name,
                    category=str(raw.get("category") or "fact"),
                    importance=imp,
                    active_project_slug=active_project_slug,
                    source_session_id=source_session_id,
                    source_message_id=source_message_id,
                    supersede_hint=raw.get("supersedes_hint"),
                    confidence=conf,
                    confidence_source=conf_src,
                    valid_from=valid_from,
                )
                saved += 1
            except Exception as e:
                logger.warning("Mnemos note persist failed: %s", e)
        return saved


mnemos_orchestrator = MnemosOrchestrator()
