"""API interne approve/reject piani orchestrazione (HITL)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.api.auth_login import (
    ChatAuthIdentity,
    password_auth_enabled,
    require_chat_auth,
)
from src.api.research import resolve_research_owner
from src.data.engine import get_async_session_maker
from src.data.models import Conversation
from src.identity import sanitize_user_id
from src.runtime import orchestration_db as odb
from src.runtime.orchestration_tools import (
    format_plan_tasks_excerpt,
    run_mark_task_completed,
    setup_execution_plan_from_markdown,
)
from src.runtime.plan_engine import next_pending_task_id
from src.runtime.plan_wait_registry import resolve_plan
from src.runtime.redis_client import redis_enqueue_session_event
from src.a2a.plan_markdown import (
    is_degenerate_plan_json,
    markdown_to_plan,
    normalize_approved_payload,
    resolve_plan_markdown_lenient,
)

router = APIRouter(prefix="/internal/orchestration", tags=["orchestration"])
logger = logging.getLogger("aion.api.orchestration")


def _nonempty_todos(items: Any) -> list:
    """Treat ``[]`` from the client as absent — never wipe DB todos with an empty list."""
    if not items or not isinstance(items, list):
        return []
    return items


def _todos_for_resolve(
    *,
    meta_todos: Any,
    body_todos: Any,
    prev_record: Optional[Dict[str, Any]],
) -> list:
    for src in (
        _nonempty_todos(meta_todos),
        _nonempty_todos(body_todos),
    ):
        if src:
            if len(src) == 1 and isinstance(src[0], dict):
                fake = {"tasks": [src[0]]}
                if is_degenerate_plan_json(fake):
                    continue
            return src
    if prev_record and prev_record.get("todos_json"):
        try:
            loaded = json.loads(prev_record["todos_json"]) or []
        except Exception:
            loaded = []
        if loaded and not (
            len(loaded) == 1
            and isinstance(loaded[0], dict)
            and is_degenerate_plan_json({"tasks": [loaded[0]]})
        ):
            return loaded
    return []


def _http_from_resolve_result(res: Dict[str, Any]) -> HTTPException:
    """Mappa errori resolve_plan (Redis / stato piano) in HTTPException leggibili."""
    err = str(res.get("error") or "resolve_failed")
    detail = res.get("detail")
    msg = f"{err}: {detail}" if detail else err
    if err in ("redis_unavailable", "redis_write_failed"):
        return HTTPException(
            status_code=503,
            detail=(
                f"{msg} — Impossibile leggere/scrivere lo stato HITL su Redis. "
                "Controlla AION_REDIS_URL e la rete; per un solo processo uvicorn senza Redis "
                "imposta AION_REDIS_FALLBACK_LOCAL=1 (vedi log server all'avvio)."
            ),
        )
    return HTTPException(status_code=400, detail=msg)


def _expected_secret() -> str:
    return (
        os.getenv("AION_ORCHESTRATION_INTERNAL_SECRET") or "aion-orchestration-dev"
    ).strip()


def _orchestration_secret_auth_enabled() -> bool:
    return os.getenv("AION_ORCHESTRATION_SECRET_AUTH", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


async def orchestration_auth(
    x_aion_orch_secret: Optional[str] = Header(None, alias="X-AION-Orch-Secret"),
    auth: ChatAuthIdentity = Depends(require_chat_auth),
) -> ChatAuthIdentity:
    """JWT for chat-ui; ``X-AION-Orch-Secret`` for legacy server-to-server when enabled."""
    if (
        x_aion_orch_secret or ""
    ).strip() == _expected_secret() and _orchestration_secret_auth_enabled():
        return ChatAuthIdentity(via="orch_secret", identifier="internal")
    if password_auth_enabled() and auth.via == "anonymous":
        raise HTTPException(
            status_code=401, detail="Authentication required for orchestration"
        )
    return auth


async def _assert_session_owner(
    session_id: str,
    auth: ChatAuthIdentity,
    x_aion_user_id: Optional[str] = None,
) -> None:
    if auth.via == "orch_secret":
        return
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    expected = resolve_research_owner(auth, x_aion_user_id)
    async with get_async_session_maker()() as db:
        row = (
            await db.execute(select(Conversation.user_id).where(Conversation.id == sid))
        ).first()
    if not row:
        if not password_auth_enabled():
            return
        raise HTTPException(status_code=404, detail="Conversation not found")
    owner = sanitize_user_id(str(row[0] or ""))
    if owner != expected:
        raise HTTPException(
            status_code=403, detail="Session does not belong to this user"
        )


class PlanSessionBody(BaseModel):
    session_id: str = Field(..., min_length=4, max_length=128)


class TaskProgressBody(PlanSessionBody):
    """Body for task completion endpoints (session_id only)."""


class PlanDecisionBody(PlanSessionBody):
    approved_plan: Optional[Dict[str, Any]] = None
    approved_markdown: Optional[str] = None
    todos: Optional[list[Dict[str, Any]]] = None
    annotations: Optional[Dict[str, Any]] = None
    approve_only: bool = False
    reason: Optional[str] = None
    user_id: Optional[str] = None
    profile_name: Optional[str] = None


@router.get("/sessions/{session_id}/plans")
async def list_session_plans(
    session_id: str,
    auth: ChatAuthIdentity = Depends(orchestration_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    """Elenco piani registrati per la sessione (plan_id tipo `execution_plan_abc12345`)."""
    await _assert_session_owner(session_id, auth, x_aion_user_id)
    plans = await odb.list_plans_for_session(session_id.strip())
    return {"session_id": session_id.strip(), "plans": plans}


@router.get("/plans/{plan_id}")
async def get_plan_state(
    plan_id: str,
    session_id: str,
    auth: ChatAuthIdentity = Depends(orchestration_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    await _assert_session_owner(session_id, auth, x_aion_user_id)
    bundle = await odb.fetch_plan_sse_bundle(plan_id)
    if (
        not bundle
        or str(bundle.get("session_id") or "").strip() != (session_id or "").strip()
    ):
        raise HTTPException(status_code=404, detail="Plan not found for session")
    status = str(bundle.get("status") or "")
    revision = int(bundle.get("revision") or 1)
    markdown = str(bundle.get("plan_markdown") or "").strip()
    plan = bundle.get("plan") if isinstance(bundle.get("plan"), dict) else {}
    return {
        "plan_id": plan_id,
        "status": status,
        "revision": revision,
        "markdown": markdown,
        "plan": plan,
        "todos": bundle.get("todos") or [],
        "annotations": bundle.get("annotations") or {},
        "locked": status == "approved",
    }


@router.post("/plans/{plan_id}/tasks/{task_id}/complete")
async def complete_plan_task(
    plan_id: str,
    task_id: str,
    body: TaskProgressBody,
    auth: ChatAuthIdentity = Depends(orchestration_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    """Marca una task come completata (checkbox `- [x]`) e aggiorna la sidebar."""
    await _assert_session_owner(body.session_id, auth, x_aion_user_id)
    stored = await odb.fetch_plan_session(plan_id)
    if not stored or stored != body.session_id.strip():
        raise HTTPException(status_code=404, detail="Plan not found for session")
    try:
        msg = await run_mark_task_completed(
            plan_id,
            task_id.strip(),
            session_id=body.session_id.strip(),
            user_id="ui",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok", "message": msg}


@router.post("/plans/{plan_id}/tasks/complete-all")
async def complete_all_plan_tasks(
    plan_id: str,
    body: TaskProgressBody,
    auth: ChatAuthIdentity = Depends(orchestration_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    """Marca tutte le task ancora aperte come completate."""
    await _assert_session_owner(body.session_id, auth, x_aion_user_id)
    stored = await odb.fetch_plan_session(plan_id)
    if not stored or stored != body.session_id.strip():
        raise HTTPException(status_code=404, detail="Plan not found for session")
    rec = await odb.fetch_plan_record(plan_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Plan record not found")
    md = (rec.get("approved_markdown") or rec.get("draft_markdown") or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="Plan has no markdown")
    import re

    unchecked_re = re.compile(r"^\s*-\s*\[\s\]\s*`([^`]+)`")
    task_ids: list[str] = []
    for line in md.splitlines():
        m = unchecked_re.match(line)
        if m:
            task_ids.append(m.group(1).strip())
    if not task_ids:
        return {
            "status": "ok",
            "completed": [],
            "errors": [],
            "message": "No unchecked tasks",
        }
    completed: list[str] = []
    errors: list[str] = []
    for tid in task_ids:
        try:
            await run_mark_task_completed(
                plan_id,
                tid,
                session_id=body.session_id.strip(),
                user_id="ui",
            )
            completed.append(tid)
        except Exception as e:
            errors.append(f"{tid}: {e}")
    if not completed and errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return {"status": "ok", "completed": completed, "errors": errors}


@router.post("/plans/{plan_id}/approve")
async def approve_plan(
    plan_id: str,
    body: PlanDecisionBody,
    auth: ChatAuthIdentity = Depends(orchestration_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    await _assert_session_owner(body.session_id, auth, x_aion_user_id)
    logger.info(
        "approve_plan START plan_id=%s session=%s approve_only=%s",
        plan_id,
        body.session_id,
        body.approve_only,
    )
    sid = body.session_id.strip()
    stored = await odb.fetch_plan_session(plan_id)
    if not stored or stored != sid:
        recovery_md = (body.approved_markdown or "").strip()
        if recovery_md:
            logger.warning(
                "approve_plan: plan %s missing in DB for session %s — re-registering from client markdown",
                plan_id,
                sid,
            )
            uid = (body.user_id or "ui").strip() or "ui"
            if await setup_execution_plan_from_markdown(
                recovery_md,
                plan_id=plan_id,
                session_id=sid,
                user_id=uid,
            ):
                stored = await odb.fetch_plan_session(plan_id)
        if not stored or stored != sid:
            raise HTTPException(status_code=404, detail="Plan not found for session")
    prev = await odb.fetch_plan_record(plan_id)
    # Inizializzazione early per evitare NameError (BUG #1)
    meta: Dict[str, Any] = {}
    approved_md: Optional[str] = None
    parsed = None
    approved_payload: Any = None
    if not body.approve_only:
        if body.approved_markdown and body.approved_markdown.strip():
            approved_payload = {
                "plan_markdown": body.approved_markdown,
                "todos": body.todos or [],
                "annotations": body.annotations or {},
            }
        elif body.approved_plan is not None:
            approved_payload = body.approved_plan
    plan_json_fallback: Optional[Dict[str, Any]] = None
    if prev:
        for key in ("approved_json", "draft_json"):
            raw_pj = prev.get(key)
            if not raw_pj:
                continue
            try:
                plan_json_fallback = (
                    json.loads(raw_pj) if isinstance(raw_pj, str) else raw_pj
                )
                if isinstance(plan_json_fallback, dict) and plan_json_fallback.get(
                    "tasks"
                ):
                    if is_degenerate_plan_json(plan_json_fallback):
                        plan_json_fallback = None
                        continue
                    break
            except Exception:
                plan_json_fallback = None
    if approved_payload is not None:
        try:
            approved_md, meta = normalize_approved_payload(approved_payload)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid approved markdown/plan: {e}"
            ) from e
        todos_for_resolve = _todos_for_resolve(
            meta_todos=meta.get("todos"),
            body_todos=body.todos,
            prev_record=prev,
        )
        approved_md, parsed = resolve_plan_markdown_lenient(
            approved_md,
            todos=todos_for_resolve,
            plan_json=plan_json_fallback,
        )
        logger.info(
            "approve_plan parsed=%d tasks plan_id=%s", len(parsed.tasks), plan_id
        )
    else:
        logger.info("approve_plan approve_only or empty payload plan_id=%s", plan_id)
        if prev:
            fallback = (
                prev.get("approved_markdown") or prev.get("draft_markdown") or ""
            ).strip()
            if fallback:
                todos_for_resolve = _todos_for_resolve(
                    meta_todos=None,
                    body_todos=body.todos,
                    prev_record=prev,
                )
                approved_md, parsed = resolve_plan_markdown_lenient(
                    fallback,
                    todos=todos_for_resolve,
                    plan_json=plan_json_fallback,
                )
    diff_meta: Dict[str, Any] = {}
    new_todos: list = body.todos or []
    try:
        old_todos = []
        if prev and prev.get("todos_json"):
            old_todos = json.loads(prev["todos_json"]) or []
        if not new_todos and parsed:
            from src.a2a.plan_markdown import plan_to_todos

            new_todos = plan_to_todos(parsed)

        old_ids = {str(t.get("id")) for t in old_todos if isinstance(t, dict)}
        new_ids = {str(t.get("id")) for t in new_todos if isinstance(t, dict)}
        diff_meta = {
            "added": sorted(new_ids - old_ids),
            "removed": sorted(old_ids - new_ids),
            "old_count": len(old_ids),
            "new_count": len(new_ids),
        }
    except Exception:
        diff_meta = {}
    logger.info("approve_plan resolve_plan START plan_id=%s", plan_id)
    res = await resolve_plan(
        plan_id,
        session_id=body.session_id.strip(),
        approved=True,
        approved_plan=approved_payload,
    )
    if not res.get("ok"):
        raise _http_from_resolve_result(res)

    final_markdown = (approved_md or "").strip()
    if not final_markdown and prev:
        final_markdown = (
            prev.get("draft_markdown") or prev.get("approved_markdown") or ""
        ).strip()
    if final_markdown and parsed is None:
        todos_for_resolve = _todos_for_resolve(
            meta_todos=None,
            body_todos=body.todos,
            prev_record=prev,
        )
        final_markdown, parsed = resolve_plan_markdown_lenient(
            final_markdown,
            todos=todos_for_resolve,
            plan_json=plan_json_fallback,
        )
    annotations = meta.get("annotations", {}) if meta else {}
    final_plan_dict = json.loads(parsed.model_dump_json()) if parsed else None
    base_rev = int(prev.get("revision") or 1) if prev else 1
    approve_revision = base_rev + 1

    try:
        await odb.update_plan_after_wait(
            plan_id,
            status="approved",
            approved_json=final_plan_dict,
            approved_markdown=final_markdown,
            annotations=annotations,
            todos=new_todos,
            audit_meta={"via": "api_direct"},
            revision=approve_revision,
        )
        logger.info("approve_plan DB updated plan_id=%s", plan_id)
    except Exception as e:
        logger.warning(f"Failed to update plan db in approve_plan: {e}")

    # BUG #2 fix: wrap insert_audit in try/except
    try:
        await odb.insert_audit(
            plan_id,
            body.session_id.strip(),
            actor="api",
            action="plan_approved",
            payload={
                "approve_only": body.approve_only,
                "has_markdown": bool(approved_md),
                "todos_diff": diff_meta,
            },
        )
        logger.info("approve_plan audit logged plan_id=%s", plan_id)
    except Exception as e:
        logger.error(
            "approve_plan insert_audit FAILED plan_id=%s: %s", plan_id, e, exc_info=True
        )

    # Invia messaggio di sistema per svegliare l'agente (visto che l'attesa asincrona del tool è stata rimossa)
    from src.runtime.tool_events import tool_event_bus

    tasks_excerpt = format_plan_tasks_excerpt(final_markdown) if final_markdown else ""
    agent_msg = (
        f"Plan `{plan_id}` was APPROVED (revision={approve_revision}).\n\n"
        "Execute **one task at a time**. After each task call **mark_task_completed** "
        f"with `plan_id`=`{plan_id}` and `task_id` from the row (e.g. `task_01`), then **STOP**.\n\n"
        "Markdown deliverable: one file under `workspace/` (see `## Deliverable` in the plan). "
        "Create it once; later tasks use **sandbox_edit_workspace_file** only — never rewrite the full file.\n\n"
        "Source of truth: orchestration DB / sidebar Plan — **do not** read `workspace/execution_plan_*.md`.\n"
        "Each **mark_task_completed** reports remaining steps. "
        "**list_session_execution_plans** / **get_execution_plan** to find the active plan — "
        "do not glob execution_plan_*.md in workspace.\n\n"
        "**Node/docx:** use `sandbox_install_npm_packages` + `sandbox_run_node_file` for .js — "
        "**not** `sandbox_exec_allowlisted` (exec policy is often disabled).\n"
    )
    if tasks_excerpt:
        agent_msg += f"\n## Tasks (approval snapshot)\n{tasks_excerpt}\n"
    next_tid = next_pending_task_id(final_markdown) if final_markdown else None
    if next_tid:
        agent_msg += (
            f"\n**Current task:** execute ONLY `{next_tid}` in this turn. "
            "Call **mark_task_completed** when done, then stop — the next task runs in a new turn.\n"
        )

    run_id = None
    ui_event = None
    if not body.approve_only and next_tid:
        from src.plan_execution.handler import (
            get_plan_execution_handler,
            plan_execution_enabled,
        )

        if plan_execution_enabled():
            try:
                owner = (body.user_id or "default").strip() or "default"
                profile = (body.profile_name or "").strip()
                started = get_plan_execution_handler().start_plan_execution(
                    plan_id,
                    owner=owner,
                    chat_session_id=body.session_id.strip(),
                    profile_name=profile,
                )
                run_id = started.get("run_id")
                ui_event = started.get("ui_event")
            except Exception as e:
                logger.warning(
                    "approve_plan start_plan_execution failed plan_id=%s: %s",
                    plan_id,
                    e,
                )

    evt = {
        "type": "orchestration_plan_approved",
        "plan_id": plan_id,
        "status": "approved",
        "approved_markdown": final_markdown or approved_md,
        "revision": approve_revision,
        "message": agent_msg,
        "next_pending_task_id": next_tid,
        "run_id": run_id,
        "ui_event": ui_event or "plan_execution_started",
    }
    tool_event_bus.put_event(body.session_id.strip(), evt)
    try:
        await redis_enqueue_session_event(body.session_id.strip(), evt)
    except Exception as e:
        logger.warning(
            "approve_plan redis_enqueue_session_event failed plan_id=%s: %s", plan_id, e
        )

    logger.info(
        "approve_plan DONE plan_id=%s status=approved run_id=%s", plan_id, run_id
    )
    return {
        "status": "ok",
        "state": res.get("state"),
        "plan": res.get("plan"),
        "plan_id": plan_id,
        "revision": approve_revision,
        "next_pending_task_id": next_tid,
        "run_id": run_id,
        "ui_event": ui_event or "plan_execution_started",
    }


@router.post("/plans/{plan_id}/reject")
async def reject_plan(
    plan_id: str,
    body: PlanDecisionBody,
    auth: ChatAuthIdentity = Depends(orchestration_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
):
    await _assert_session_owner(body.session_id, auth, x_aion_user_id)
    stored = await odb.fetch_plan_session(plan_id)
    if not stored or stored != body.session_id.strip():
        raise HTTPException(status_code=404, detail="Plan not found for session")
    res = await resolve_plan(
        plan_id,
        session_id=body.session_id.strip(),
        approved=False,
        reason=body.reason or "rejected_by_user",
    )
    if not res.get("ok"):
        raise _http_from_resolve_result(res)

    try:
        await odb.update_plan_after_wait(
            plan_id,
            status="rejected",
            audit_meta={"reason": body.reason or "rejected_by_user"},
        )
    except Exception as e:
        logger.warning(f"Failed to update plan db in reject_plan: {e}")

    try:
        await odb.insert_audit(
            plan_id,
            body.session_id.strip(),
            actor="api",
            action="plan_rejected",
            payload={"reason": body.reason},
        )
    except Exception as e:
        logger.error(
            "reject_plan insert_audit FAILED plan_id=%s: %s", plan_id, e, exc_info=True
        )

    # Invia messaggio di sistema per svegliare l'agente
    from src.runtime.tool_events import tool_event_bus

    evt = {
        "type": "orchestration_plan_rejected",
        "plan_id": plan_id,
        "status": "rejected",
        "message": f"ATTENTION: Execution plan '{plan_id}' was REJECTED by the user. Reason: {body.reason}. Propose changes or ask for clarification.",
    }
    tool_event_bus.put_event(body.session_id.strip(), evt)
    try:
        await redis_enqueue_session_event(body.session_id.strip(), evt)
    except Exception as e:
        logger.warning(
            "reject_plan redis_enqueue_session_event failed plan_id=%s: %s", plan_id, e
        )

    return {"status": "ok", "state": res.get("state")}
