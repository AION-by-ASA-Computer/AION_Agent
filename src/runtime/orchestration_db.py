"""Persistenza piani orchestrazione (SQLAlchemy async)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update

from src.data.engine import get_async_session_maker
from src.data.models import ExecutionPlanRecord, OrchestrationAudit

logger = logging.getLogger("aion.orchestration_db")


async def _supersede_other_session_drafts(session, session_id: str, plan_id: str) -> None:
    """Supersede draft_pending plans for this session except the target plan_id."""
    await session.execute(
        update(ExecutionPlanRecord)
        .where(
            ExecutionPlanRecord.session_id == session_id,
            ExecutionPlanRecord.status == "draft_pending",
            ExecutionPlanRecord.plan_id != plan_id,
        )
        .values(status="superseded")
    )


async def upsert_execution_plan_draft(
    plan_id: str,
    session_id: str,
    user_id: str,
    draft: Dict[str, Any],
    *,
    draft_markdown: str | None = None,
    todos: Optional[list[Dict[str, Any]]] = None,
    status: str = "draft_pending",
) -> bool:
    """Insert or refresh a draft plan. Returns False if plan_id belongs to another session."""
    pid = (plan_id or "").strip()
    sid = (session_id or "").strip()
    if not pid or not sid:
        return False
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(ExecutionPlanRecord).where(ExecutionPlanRecord.plan_id == pid)
        )
        existing = r.scalar_one_or_none()
        if existing:
            if str(existing.session_id or "").strip() != sid:
                logger.warning(
                    "upsert_execution_plan_draft: plan %s session mismatch (%s != %s)",
                    pid,
                    existing.session_id,
                    sid,
                )
                return False
            existing.draft_json = json.dumps(draft, ensure_ascii=False)
            if draft_markdown is not None:
                existing.draft_markdown = draft_markdown
            if todos is not None:
                existing.todos_json = json.dumps(todos, ensure_ascii=False)
            if existing.status in ("superseded", "draft_pending", "rejected"):
                existing.status = status
            await _supersede_other_session_drafts(session, sid, pid)
            await session.commit()
            return True
        await _supersede_other_session_drafts(session, sid, pid)
        row = ExecutionPlanRecord(
            plan_id=pid,
            session_id=sid,
            user_id=user_id,
            status=status,
            draft_json=json.dumps(draft, ensure_ascii=False),
            draft_markdown=draft_markdown,
            todos_json=json.dumps(todos, ensure_ascii=False) if todos is not None else None,
        )
        session.add(row)
        await session.commit()
        return True


async def insert_execution_plan(
    plan_id: str,
    session_id: str,
    user_id: str,
    draft: Dict[str, Any],
    *,
    draft_markdown: str | None = None,
    todos: Optional[list[Dict[str, Any]]] = None,
    status: str = "draft_pending",
) -> None:
    ok = await upsert_execution_plan_draft(
        plan_id,
        session_id,
        user_id,
        draft,
        draft_markdown=draft_markdown,
        todos=todos,
        status=status,
    )
    if not ok:
        raise ValueError(f"plan {plan_id} already registered for a different session")


async def update_plan_after_wait(
    plan_id: str,
    *,
    status: str,
    draft_markdown: Optional[str] = None,
    approved_json: Optional[Dict[str, Any]] = None,
    approved_markdown: Optional[str] = None,
    annotations: Optional[Dict[str, Any]] = None,
    todos: Optional[list[Dict[str, Any]]] = None,
    audit_meta: Optional[Dict[str, Any]] = None,
    revision: Optional[int] = None,
) -> None:
    maker = get_async_session_maker()
    async with maker() as session:
        vals: Dict[str, Any] = {"status": status}
        if approved_json is not None:
            vals["approved_json"] = json.dumps(approved_json, ensure_ascii=False)
            vals["approved_at"] = datetime.now(timezone.utc)
        if draft_markdown is not None:
            vals["draft_markdown"] = draft_markdown
        if approved_markdown is not None:
            vals["approved_markdown"] = approved_markdown
            vals["approved_at"] = datetime.now(timezone.utc)
        if annotations is not None:
            vals["annotations_json"] = json.dumps(annotations, ensure_ascii=False)
        if todos is not None:
            vals["todos_json"] = json.dumps(todos, ensure_ascii=False)
        if audit_meta is not None:
            vals["audit_meta_json"] = json.dumps(audit_meta, ensure_ascii=False)  # ORM → colonna audit_meta
        if revision is not None:
            vals["revision"] = int(revision)
        await session.execute(update(ExecutionPlanRecord).where(ExecutionPlanRecord.plan_id == plan_id).values(**vals))
        await session.commit()


async def fetch_plan_session(plan_id: str) -> Optional[str]:
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(select(ExecutionPlanRecord.session_id).where(ExecutionPlanRecord.plan_id == plan_id))
        row = r.first()
        return str(row[0]) if row else None


async def fetch_plan_record(plan_id: str) -> Optional[Dict[str, Any]]:
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(
                ExecutionPlanRecord.draft_markdown,
                ExecutionPlanRecord.approved_markdown,
                ExecutionPlanRecord.todos_json,
                ExecutionPlanRecord.annotations_json,
                ExecutionPlanRecord.revision,
            ).where(ExecutionPlanRecord.plan_id == plan_id)
        )
        row = r.first()
        if not row:
            return None
        return {
            "draft_markdown": row[0],
            "approved_markdown": row[1],
            "todos_json": row[2],
            "annotations_json": row[3],
            "revision": row[4],
        }


async def fetch_plan_sse_bundle(plan_id: str) -> Optional[Dict[str, Any]]:
    """Payload completo per ripristinare chat-ui/SSE (markdown, revision, session_id, todos, annotations)."""
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(
                ExecutionPlanRecord.session_id,
                ExecutionPlanRecord.status,
                ExecutionPlanRecord.draft_json,
                ExecutionPlanRecord.approved_json,
                ExecutionPlanRecord.draft_markdown,
                ExecutionPlanRecord.approved_markdown,
                ExecutionPlanRecord.todos_json,
                ExecutionPlanRecord.annotations_json,
                ExecutionPlanRecord.revision,
            ).where(ExecutionPlanRecord.plan_id == plan_id)
        )
        row = r.first()
        if not row:
            return None
        sid, status, draft_json_s, appr_json_s, draft_md, appr_md, todos_s, ann_s, rev = row
        md = (appr_md or draft_md or "").strip()
        if not md:
            return None
        todos: list = []
        if todos_s:
            try:
                todos = json.loads(todos_s) or []
            except Exception:
                todos = []
        annotations: Dict[str, Any] = {}
        if ann_s:
            try:
                annotations = json.loads(ann_s) or {}
            except Exception:
                annotations = {}
        plan_dict: Dict[str, Any] = {}
        src = appr_json_s or draft_json_s
        if src:
            try:
                plan_dict = json.loads(src) or {}
            except Exception:
                plan_dict = {}
        return {
            "session_id": str(sid or ""),
            "status": str(status or ""),
            "plan_markdown": md,
            "plan": plan_dict,
            "todos": todos,
            "annotations": annotations,
            "revision": int(rev or 1),
        }


async def list_plans_for_session(session_id: str, *, limit: int = 20) -> list[Dict[str, Any]]:
    """Piani orchestrazione per sessione (più recenti prima), esclusi i superseded."""
    sid = (session_id or "").strip()
    if not sid:
        return []
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(
                ExecutionPlanRecord.plan_id,
                ExecutionPlanRecord.status,
                ExecutionPlanRecord.revision,
                ExecutionPlanRecord.approved_at,
            )
            .where(
                ExecutionPlanRecord.session_id == sid,
                ExecutionPlanRecord.status != "superseded",
            )
            .order_by(ExecutionPlanRecord.created_at.desc(), ExecutionPlanRecord.plan_id.desc())
            .limit(max(1, min(limit, 50)))
        )
        rows = r.all()
    return [
        {
            "plan_id": str(row[0]),
            "status": str(row[1] or ""),
            "revision": int(row[2] or 1),
        }
        for row in rows
    ]


async def fetch_plan_state(plan_id: str) -> Optional[Dict[str, Any]]:
    maker = get_async_session_maker()
    async with maker() as session:
        r = await session.execute(
            select(
                ExecutionPlanRecord.session_id,
                ExecutionPlanRecord.status,
                ExecutionPlanRecord.draft_markdown,
                ExecutionPlanRecord.approved_markdown,
                ExecutionPlanRecord.revision,
            ).where(ExecutionPlanRecord.plan_id == plan_id)
        )
        row = r.first()
        if not row:
            return None
        return {
            "session_id": row[0],
            "status": row[1],
            "draft_markdown": row[2],
            "approved_markdown": row[3],
            "revision": row[4],
        }


async def insert_audit(
    plan_id: str,
    session_id: str,
    actor: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    maker = get_async_session_maker()
    async with maker() as session:
        session.add(
            OrchestrationAudit(
                plan_id=plan_id,
                session_id=session_id,
                actor=actor,
                action=action,
                payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            )
        )
        await session.commit()
