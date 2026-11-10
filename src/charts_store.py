"""Durable storage of session charts in SQLite (``session_charts`` table).

Charts are first held in the live store (``src/chart_queue.py``, Redis or
memory) and streamed to chat-ui as ``chart`` SSE events. At the end of the SSE
turn the agent pipeline calls :func:`persist_turn_charts` so the charts survive a
reload / chat switch and can be re-rendered inline in the assistant timeline.

Used by:

* ``src/agent_pipeline.py`` — persist at turn end;
* ``src/api/chat_ui.py`` — hydrate chart segments in the message history and
  delete charts when a conversation or turn is deleted;
* ``src/api/v1/conversations.py`` — delete charts on conversation delete.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, select

from src.data.engine import get_async_session_maker
from src.data.models import SessionChart

logger = logging.getLogger("aion.charts_store")


def _tenant() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


async def persist_turn_charts(
    conversation_id: str,
    message_id: Optional[str],
    charts: Iterable[Dict[str, Any]],
) -> int:
    """Upsert the charts produced in a turn, linked to the assistant message.

    Idempotent on chart ``id`` (a retried flush does not duplicate rows).
    Returns the number of rows written; errors are logged, never raised, so a DB
    hiccup cannot break the end of the SSE stream.
    """
    items = [c for c in charts if isinstance(c, dict) and c.get("id")]
    if not items:
        return 0
    written = 0
    try:
        async with get_async_session_maker()() as session:
            for chart in items:
                cid = str(chart["id"])
                payload = json.dumps(chart, ensure_ascii=False, default=str)
                row = await session.get(SessionChart, cid)
                if row is None:
                    session.add(
                        SessionChart(
                            id=cid,
                            conversation_id=conversation_id,
                            tenant_id=_tenant(),
                            message_id=message_id,
                            tool_call_id=chart.get("tool_call_id"),
                            payload_json=payload,
                        )
                    )
                else:
                    row.payload_json = payload
                    row.message_id = message_id or row.message_id
                written += 1
            await session.commit()
    except Exception as exc:
        logger.warning(
            "persist_turn_charts failed (session=%s): %s", conversation_id[:12], exc
        )
        return 0
    return written


async def load_conversation_charts(
    conversation_id: str,
) -> List[Dict[str, Any]]:
    """Return persisted charts of a conversation, oldest first.

    Each dict is the stored payload plus ``id``, ``message_id`` and
    ``tool_call_id`` (columns win over payload keys).
    """
    try:
        async with get_async_session_maker()() as session:
            rows = (
                (
                    await session.execute(
                        select(SessionChart)
                        .where(SessionChart.conversation_id == conversation_id)
                        .order_by(SessionChart.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
    except Exception as exc:
        logger.warning("load_conversation_charts failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json or "{}")
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload["id"] = r.id
        if r.message_id:
            payload["message_id"] = r.message_id
        if r.tool_call_id:
            payload["tool_call_id"] = r.tool_call_id
        out.append(payload)
    return out


async def delete_conversation_charts(conversation_ids: Iterable[str]) -> None:
    """Remove charts (SQLite rows + live Redis/memory store) of whole conversations.

    Conversations are soft-deleted (``archived_at``), so the FK cascade does not
    fire: this keeps the chart history from outliving the chat the user deleted.
    """
    ids = [c for c in conversation_ids if c]
    if not ids:
        return
    try:
        async with get_async_session_maker()() as session:
            await session.execute(
                delete(SessionChart).where(SessionChart.conversation_id.in_(ids))
            )
            await session.commit()
    except Exception as exc:
        logger.warning("delete_conversation_charts failed: %s", exc)
    from src.chart_queue import chart_queue

    for cid in ids:
        chart_queue.clear(cid)


async def delete_message_charts(
    conversation_id: str, message_ids: Iterable[str], session: Any = None
) -> None:
    """Remove charts attached to the given messages (turn deletion).

    When ``session`` is given the delete joins the caller's transaction.
    The live store is cleared too: it only holds the current turns' charts and
    stale entries would otherwise be re-hydrated into the deleted turn.
    """
    mids = [m for m in message_ids if m]
    if not mids:
        return
    stmt = delete(SessionChart).where(
        SessionChart.conversation_id == conversation_id,
        SessionChart.message_id.in_(mids),
    )
    if session is not None:
        await session.execute(stmt)
    else:
        try:
            async with get_async_session_maker()() as own:
                await own.execute(stmt)
                await own.commit()
        except Exception as exc:
            logger.warning("delete_message_charts failed: %s", exc)
    from src.chart_queue import chart_queue

    chart_queue.clear(conversation_id)
