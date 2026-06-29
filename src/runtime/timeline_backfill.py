"""Idempotent backfill of messages.timeline_json from legacy flat fields."""
from __future__ import annotations

import logging
import os
from typing import List

from sqlalchemy import create_engine, inspect, select

from src.data.engine import get_async_session_maker
from src.data.migrations import _to_sync_db_url
from src.data.message_roles import normalize_message_role
from src.data.models import Attachment, Message, Step
from src.runtime.timeline_reconstruct import timeline_json_from_legacy

logger = logging.getLogger("aion.runtime.timeline_backfill")


def _messages_has_timeline_column() -> bool:
    sync_url = _to_sync_db_url((os.getenv("AION_DB_URL") or "").strip())
    if not sync_url:
        return False
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            cols = {c["name"] for c in inspect(conn).get_columns("messages")}
            return "timeline_json" in cols
    except Exception as exc:
        logger.debug("timeline_json column check skipped: %s", exc)
        return False
    finally:
        engine.dispose()


async def backfill_message_timelines(*, batch_size: int = 200, dry_run: bool = False) -> int:
    """Populate timeline_json for assistant messages where it is still null."""
    if not _messages_has_timeline_column():
        logger.info("messages.timeline_json not present; skip timeline backfill")
        return 0

    updated = 0
    async with get_async_session_maker()() as session:
        q_msg = select(Message).where(Message.timeline_json.is_(None))
        msgs = (await session.execute(q_msg)).scalars().all()
        assistant_msgs = [m for m in msgs if normalize_message_role(m.role) == "assistant"]
        if not assistant_msgs:
            return 0

        conv_ids = {m.conversation_id for m in assistant_msgs}
        steps_by_msg: dict[str, list] = {}
        atts_by_msg: dict[str, list] = {}

        for cid in conv_ids:
            q_steps = select(Step).where(Step.conversation_id == cid).order_by(Step.created_at.asc())
            for s in (await session.execute(q_steps)).scalars().all():
                mid = s.message_id or "orphan"
                steps_by_msg.setdefault(mid, []).append(
                    {
                        "id": s.id,
                        "name": s.name,
                        "type": s.type,
                        "input": s.input,
                        "output": s.output,
                        "is_error": bool(s.is_error),
                        "metadata_json": s.metadata_json,
                        "created_at": s.created_at,
                    }
                )
            q_att = select(Attachment).where(Attachment.conversation_id == cid).order_by(
                Attachment.created_at.asc()
            )
            for a in (await session.execute(q_att)).scalars().all():
                mid = a.message_id or "orphan"
                atts_by_msg.setdefault(mid, []).append(
                    {
                        "id": a.id,
                        "storage_key": a.storage_key,
                        "original_name": a.original_name,
                        "mime": a.mime,
                        "size_bytes": a.size_bytes,
                        "kind": a.kind,
                        "created_at": a.created_at,
                    }
                )

        by_conv: dict[str, List[Message]] = {}
        for m in assistant_msgs:
            by_conv.setdefault(m.conversation_id, []).append(m)

        for _conv_id, conv_msgs in by_conv.items():
            conv_msgs.sort(key=lambda x: x.seq)
            orphan_steps = list(steps_by_msg.get("orphan", []))
            orphan_atts = list(atts_by_msg.get("orphan", []))
            for m in conv_msgs:
                steps = list(steps_by_msg.get(m.id, []))
                atts = list(atts_by_msg.get(m.id, []))
                final_steps = orphan_steps + steps
                final_atts = orphan_atts + atts
                orphan_steps = []
                orphan_atts = []
                tj = timeline_json_from_legacy(
                    reasoning=m.reasoning,
                    content=m.content,
                    steps=final_steps,
                    artifacts=final_atts,
                )
                if not tj or tj == "[]":
                    continue
                if dry_run:
                    updated += 1
                    continue
                m.timeline_json = tj
                updated += 1
                if updated % batch_size == 0:
                    await session.commit()

        if not dry_run and updated:
            await session.commit()
    return updated
