"""Execute scheduled jobs headless (no SSE)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

from src.agent_pipeline import AgentPipeline
from src.identity import sanitize_user_id
from src.main import get_agent, set_event_loop
from src.runtime import cron_db
from src.runtime.redis_client import redis_set_stream_active, redis_clear_stream_active


logger = logging.getLogger("aion.cron_runner")

_JOB_LOCKS: Dict[str, asyncio.Lock] = {}
_PREVIEW_MAX = 4000


def _preview_max() -> int:
    try:
        return max(
            500, int(os.getenv("AION_CRON_PREVIEW_MAX_CHARS", str(_PREVIEW_MAX)))
        )
    except ValueError:
        return _PREVIEW_MAX


def _job_lock(job_id: str) -> asyncio.Lock:
    if job_id not in _JOB_LOCKS:
        _JOB_LOCKS[job_id] = asyncio.Lock()
    return _JOB_LOCKS[job_id]


async def _ensure_conversation(
    *,
    conversation_id: str,
    user_id: str,
    tenant_id: str,
    profile_slug: str,
    job: Dict[str, Any],
) -> None:
    from datetime import datetime, timezone

    from src.data.engine import get_async_session_maker
    from src.data.models import Conversation

    job_name = (job.get("name") or "").strip() or f"Cron {conversation_id[:8]}"
    meta = {
        "source": "scheduled_job",
        "cron_job_id": job.get("job_id"),
        "cron_job_name": job_name,
    }

    async with get_async_session_maker()() as session:
        existing = await session.get(Conversation, conversation_id)
        if existing:
            try:
                current = json.loads(existing.metadata_json or "{}")
                if current.get("source") != "scheduled_job":
                    current["source"] = "scheduled_job"
                current.setdefault("cron_job_id", job.get("job_id"))
                current.setdefault("cron_job_name", job_name)
                existing.metadata_json = json.dumps(current)
            except Exception:
                pass
            if not (existing.title or "").strip() or (existing.title or "").startswith(
                "Cron:"
            ):
                existing.title = job_name
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
            await session.commit()
            return
        session.add(
            Conversation(
                id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                profile_slug=profile_slug,
                title=job_name,
                message_count=0,
                metadata_json=json.dumps(meta),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


async def resolve_session_for_run(job: Dict[str, Any]) -> str:
    mode = (job.get("session_mode") or "fixed").strip().lower()
    if mode == "new":
        return str(uuid.uuid4())
    sid = (job.get("session_id") or "").strip()
    if sid:
        return sid
    sid = str(uuid.uuid4())
    await cron_db.set_job_session_id(job["job_id"], sid)
    return sid


async def execute_job(job_id: str, *, trigger: str = "scheduler") -> Dict[str, Any]:
    """Run one scheduled job; returns run summary dict."""
    job = await cron_db.get_job(job_id)
    if not job:
        return {"ok": False, "error": "job_not_found", "job_id": job_id}
    if not job.get("enabled") and trigger == "scheduler":
        return {"ok": False, "error": "job_disabled", "job_id": job_id}

    lock = _job_lock(job_id)
    if lock.locked():
        logger.info("cron skip overlap job_id=%s", job_id[:8])
        return {"ok": False, "error": "already_running", "job_id": job_id}

    async with lock:
        if await cron_db.has_running_run(job_id):
            return {"ok": False, "error": "already_running", "job_id": job_id}

        user_id = sanitize_user_id(job.get("user_id"))
        tenant_id = (job.get("tenant_id") or "default").strip() or "default"
        profile = (job.get("profile_slug") or "generic_assistant").strip()
        conversation_id = await resolve_session_for_run(job)

        await _ensure_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            profile_slug=profile,
            job=job,
        )

        run_id = await cron_db.insert_run_start(
            job_id,
            session_id=conversation_id,
            conversation_id=conversation_id,
        )

        prompt = (job.get("prompt") or "").strip()
        if trigger != "scheduler":
            prompt = f"[Manual cron trigger ({trigger})]\n\n{prompt}"

        # ---------------------------------------------------------
        # 1. CREAZIONE ID MESSAGGI
        # ---------------------------------------------------------
        user_message_id = str(uuid.uuid4())
        assistant_message_id = str(uuid.uuid4())

        # 2. SALVATAGGIO PROMPT UTENTE (Così la UI vede la domanda del CRON)
        # Sostituisci con la tua funzione effettiva di salvataggio a DB
        # await save_chat_message(conversation_id, user_message_id, "user", prompt, user_id)

        # 3. ATTIVAZIONE STREAM REDIS (Innesca il polling nella UI)
        await redis_set_stream_active(
            conversation_id,
            assistant_message_id=assistant_message_id,
            user_message_id=user_message_id,
            profile_name=profile,
        )
        from src.api.v1.chat import _background_runs, BackgroundChatRun
        run = BackgroundChatRun(conversation_id)
        _background_runs[conversation_id] = run
        # ---------------------------------------------------------

        assistant_text = ""
        err_msg: Optional[str] = None
        status = "success"
        try:
            set_event_loop(asyncio.get_running_loop())
            agent_instance, profile_name = await get_agent(
                profile,
                session_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_mode=job.get("agent_mode") or "normal",
                message_source="scheduled_trigger",
            )
            pipeline = AgentPipeline(
                agent=agent_instance,
                session_id=conversation_id,
                profile_name=profile_name,
                user_id=user_id,
                agent_mode=job.get("agent_mode") or "normal",
            )
            parts: list[str] = []
            chunk_count = 0
            async for chunk in pipeline.run_stream(
                prompt,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                message_source="scheduled_trigger",
            ):
                event_data = {"event": "message", "data": json.dumps(chunk)}
                run.history.append(event_data)
                for q in list(run.queues):
                    await q.put(event_data)
                ctype = str(chunk.get("type") or "")
                if ctype == "token":
                    parts.append(str(chunk.get("content") or ""))
                elif ctype == "error":
                    err_msg = str(chunk.get("content") or "error")
                    status = "error"
                    break

                # ---------------------------------------------------------
                # 4. SALVATAGGIO INTERMEDIO (Per il Live View)
                # Ogni N chunk salviamo lo stato parziale sul DB per il polling
                # ---------------------------------------------------------
                chunk_count += 1
                if chunk_count % 8 == 0:
                    partial_text = "".join(parts).strip()
                    # Salva il messaggio parziale (Sostituisci con la tua funzione DB)
                    # await save_assistant_message(conversation_id, assistant_message_id, partial_text, user_id=user_id)

            assistant_text = "".join(parts).strip()
            if not assistant_text and not err_msg:
                assistant_text = "(no text output)"
        except Exception as e:
            logger.exception("cron run failed job_id=%s", job_id)
            err_msg = str(e)
            status = "error"

        except BaseException as e:
            logger.warning("cron run interrupted/cancelled job_id=%s: %s", job_id, e)
            err_msg = f"Cancelled/Interrupted: {type(e).__name__}"
            status = "error"
            raise
        finally:
            run.is_done = True
            for q in list(run.queues):
                await q.put(None)
            _background_runs.pop(conversation_id, None)
            # ---------------------------------------------------------
            # 6. PULIZIA REDIS
            # Diciamo alla UI che lo stream è finito e può smettere di fare polling
            # ---------------------------------------------------------
            await redis_clear_stream_active(conversation_id)

            preview = assistant_text[: _preview_max()] if assistant_text else None
            await asyncio.shield(
                cron_db.finish_run(
                    run_id,
                    status=status,
                    error_message=err_msg,
                    assistant_preview=preview,
                )
            )
            if job.get("enabled"):
                await asyncio.shield(cron_db.bump_next_run_after_fire(job_id))

        return {
            "ok": status == "success",
            "job_id": job_id,
            "run_id": run_id,
            "status": status,
            "session_id": conversation_id,
            "conversation_id": conversation_id,
            "error": err_msg,
        }
