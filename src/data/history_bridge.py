"""
Unified DB implementation of chat history (session_id == conversation.id).
Enabled when AION_UNIFIED_DB is on (default 1; migrate with `python scripts/migrate_to_aion_db.py` or fresh bootstrap).

Transcript contract (write → store → read):
- Turn IDs (user_message_id, assistant_message_id) are fixed at turn_started and immutable.
- Server pipeline + TurnPersistence are the authoritative writers for assistant/steps/attachments.
- Every step/attachment must bind to assistant_message_id for the turn.
- Compaction deletes messages and their child steps/attachments atomically, then recounts.
- GET /chat-ui/.../messages is read-only (no orphan attach, no dedup, no DB backfill).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from haystack.dataclasses import ChatMessage
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .bootstrap import ensure_bootstrap_schema
from .engine import get_async_session_maker, init_engine
from .ids import new_uuid7_str
from .message_roles import is_model_context_role, normalize_message_role
from .models import Conversation, Message, Step, Attachment

logger = logging.getLogger("aion.data.bridge")


async def fetch_message_by_id(
    session: AsyncSession, message_id: str
) -> Optional[Message]:
    """Lookup by public message UUID (Message.id), not fts_rowid PK."""
    mid = (message_id or "").strip()
    if not mid:
        return None
    row = await session.execute(select(Message).where(Message.id == mid).limit(1))
    return row.scalars().first()


async def fetch_message_by_id_for_conversation(
    session: AsyncSession, message_id: str, conversation_id: str
) -> Optional[Message]:
    """Lookup message scoped to a conversation (prevents cross-conversation upsert)."""
    mid = (message_id or "").strip()
    cid = (conversation_id or "").strip()
    if not mid or not cid:
        return None
    row = await session.execute(
        select(Message)
        .where(
            Message.id == mid,
            Message.conversation_id == cid,
        )
        .limit(1)
    )
    return row.scalars().first()


async def _delete_messages_and_children(
    session: AsyncSession,
    conversation_id: str,
    message_ids: List[str],
) -> None:
    """Delete messages and their bound steps/attachments (compaction / prune)."""
    if not message_ids:
        return
    await session.execute(delete(Step).where(Step.message_id.in_(message_ids)))
    await session.execute(
        delete(Attachment).where(Attachment.message_id.in_(message_ids))
    )
    await session.execute(delete(Message).where(Message.id.in_(message_ids)))


async def _cleanup_orphan_steps_and_attachments(
    session: AsyncSession, conversation_id: str
) -> None:
    """Remove steps/attachments with no message_id in this conversation."""
    await session.execute(
        delete(Step).where(
            Step.conversation_id == conversation_id,
            Step.message_id.is_(None),
        )
    )
    await session.execute(
        delete(Attachment).where(
            Attachment.conversation_id == conversation_id,
            Attachment.message_id.is_(None),
        )
    )


async def _recount_conversation_messages(
    session: AsyncSession, conversation_id: str
) -> int:
    count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == conversation_id)
            )
        ).scalar_one()
        or 0
    )
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(message_count=count, updated_at=datetime.now(timezone.utc))
    )
    return count


async def _fetch_last_significant_assistant_content(
    session: AsyncSession,
    conversation_id: str,
    pruned_ids: List[str],
    *,
    max_chars: int = 4000,
) -> str:
    if not pruned_ids:
        return ""
    rows = (
        await session.execute(
            select(Message.content, Message.role, Message.seq)
            .where(
                Message.conversation_id == conversation_id,
                Message.id.in_(pruned_ids),
                Message.role == "assistant",
            )
            .order_by(Message.seq.desc())
        )
    ).all()
    for content, _role, _seq in rows:
        body = (content or "").strip()
        if body:
            return body[:max_chars]
    return ""


async def _sanitize_kept_assistant_timelines(
    session: AsyncSession,
    conversation_id: str,
    kept_ids: List[str],
    *,
    timeline_size_threshold: int = 50_000,
) -> None:
    """Clear inflated timeline_json on kept assistants with no visible text."""
    if not kept_ids:
        return
    rows = (
        (
            await session.execute(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.id.in_(kept_ids),
                    Message.role == "assistant",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        if (row.content or "").strip():
            continue
        tl = row.timeline_json or ""
        if len(tl) > timeline_size_threshold:
            row.timeline_json = None
            session.add(row)


def _approx_tokens(t: str) -> int:
    return max(1, len(t) // 4)


def _conversation_title_from_user_message(content: str, max_len: int = 80) -> str:
    title = re.sub(r"\s+", " ", (content or "").strip())
    if not title:
        return ""
    if len(title) <= max_len:
        return title
    return title[: max_len - 1].rstrip() + "…"


class UnifiedHistoryBridge:
    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        eng = init_engine()
        await ensure_bootstrap_schema(eng)
        self._ready = True

    async def init(self) -> None:
        await self._ensure()

    async def _get_or_create_conv(
        self,
        session: AsyncSession,
        conversation_id: str,
        profile_name: str,
        user_id: Optional[str],
    ) -> Conversation:
        await self._ensure()
        r = await session.get(Conversation, conversation_id)
        if r:
            return r
        c = Conversation(
            id=conversation_id,
            tenant_id=self.tenant_id,
            user_id=user_id or "default",
            profile_slug=profile_name,
            title=None,
            message_count=0,
        )
        session.add(c)
        await session.flush()
        return c

    def _patch_message_row(
        self,
        row: Message,
        *,
        role: str,
        content: str,
        profile_name: str,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        timeline_json: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> None:
        row.role = role
        incoming = (content or "").strip()
        existing = (row.content or "").strip()
        if incoming or not existing:
            row.content = content
        # else: keep non-empty streamed body when a later upsert sends ""
        row.profile_name = profile_name
        if tool_name is not None:
            row.tool_name = tool_name
        if tool_call_id is not None:
            row.tool_call_id = tool_call_id
        if reasoning is not None:
            inc_r = (reasoning or "").strip()
            if inc_r or not (row.reasoning or "").strip():
                row.reasoning = reasoning
        if timeline_json is not None:
            inc_tl = (timeline_json or "").strip()
            ex_tl = (row.timeline_json or "").strip()
            if inc_tl and inc_tl not in ("[]", "null"):
                row.timeline_json = timeline_json
            elif not ex_tl:
                row.timeline_json = timeline_json
        if metadata_json is not None:
            row.metadata_json = metadata_json

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        profile_name: str = "default",
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        message_id: Optional[str] = None,
        timeline_json: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> None:
        role = normalize_message_role(role)
        mid = (message_id or "").strip() or new_uuid7_str()
        if message_id:
            await self.upsert_message_content(
                session_id,
                mid,
                role,
                content,
                profile_name=profile_name,
                user_id=user_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                reasoning=reasoning,
                timeline_json=timeline_json,
                metadata_json=metadata_json,
            )
            return

        async with get_async_session_maker()() as session:
            await self._ensure()
            conversation = await self._get_or_create_conv(
                session, session_id, profile_name, user_id
            )

            sql = text("""
                INSERT INTO messages (
                    id, conversation_id, tenant_id, seq, role, content,
                    tool_name, tool_call_id, profile_name, reasoning, timeline_json, metadata_json, created_at,
                    promoted_to_ltm
                )
                VALUES (
                    :id, :cid, :tid,
                    (SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = :cid),
                    :role, :content, :tname, :tcid, :pname, :reasoning, :timeline_json, :metadata_json, CURRENT_TIMESTAMP,
                    0
                )
            """)

            params = {
                "id": mid,
                "cid": session_id,
                "tid": self.tenant_id,
                "role": role,
                "content": content,
                "tname": tool_name,
                "tcid": tool_call_id,
                "pname": profile_name,
                "reasoning": reasoning,
                "timeline_json": timeline_json,
                "metadata_json": metadata_json,
            }

            await session.execute(sql, params)
            auto_title = (
                _conversation_title_from_user_message(content) if role == "user" else ""
            )
            if auto_title and not (conversation.title or "").strip():
                conversation.title = auto_title
            await session.execute(
                text(
                    "UPDATE conversations SET message_count = message_count + 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :cid"
                ),
                {"cid": session_id},
            )
            await session.commit()

    async def update_message_timeline(
        self, message_id: str, timeline_json: str
    ) -> None:
        async with get_async_session_maker()() as session:
            await self._ensure()
            await session.execute(
                text("UPDATE messages SET timeline_json = :tj WHERE id = :mid"),
                {"tj": timeline_json, "mid": message_id},
            )
            await session.commit()

    async def upsert_message_content(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        *,
        profile_name: str = "default",
        user_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        timeline_json: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> bool:
        """Insert or update message body (for live streaming / background turn recovery). Returns True if inserted."""
        role = normalize_message_role(role)
        mid = (message_id or "").strip()
        if not mid:
            return False

        async with get_async_session_maker()() as session:
            await self._ensure()
            conversation = await self._get_or_create_conv(
                session, session_id, profile_name, user_id
            )
            now = datetime.now(timezone.utc)

            async def _update_existing(row: Message) -> bool:
                self._patch_message_row(
                    row,
                    role=role,
                    content=content,
                    profile_name=profile_name,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    reasoning=reasoning,
                    timeline_json=timeline_json,
                    metadata_json=metadata_json,
                )
                conversation.updated_at = now
                session.add(row)
                session.add(conversation)
                await session.commit()
                return False

            existing = await fetch_message_by_id_for_conversation(
                session, mid, session_id
            )
            if not existing:
                cross = await fetch_message_by_id(session, mid)
                if cross and cross.conversation_id != session_id:
                    logger.error(
                        "upsert_message_content: message %s belongs to conversation %s, "
                        "rejecting update for %s",
                        mid,
                        cross.conversation_id,
                        session_id,
                    )
                    return False

            if existing:
                return await _update_existing(existing)

            sql = text("""
                INSERT INTO messages (
                    id, conversation_id, tenant_id, seq, role, content,
                    tool_name, tool_call_id, profile_name, reasoning, timeline_json, metadata_json, created_at,
                    promoted_to_ltm
                )
                VALUES (
                    :id, :cid, :tid,
                    (SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = :cid),
                    :role, :content, :tname, :tcid, :pname, :reasoning, :timeline_json, :metadata_json, CURRENT_TIMESTAMP,
                    0
                )
            """)
            params = {
                "id": mid,
                "cid": session_id,
                "tid": self.tenant_id,
                "role": role,
                "content": content,
                "tname": tool_name,
                "tcid": tool_call_id,
                "pname": profile_name,
                "reasoning": reasoning,
                "timeline_json": timeline_json,
                "metadata_json": metadata_json,
            }
            try:
                await session.execute(sql, params)
            except IntegrityError:
                await session.rollback()
                existing = await fetch_message_by_id_for_conversation(
                    session, mid, session_id
                )
                if not existing:
                    cross = await fetch_message_by_id(session, mid)
                    if cross and cross.conversation_id != session_id:
                        logger.error(
                            "upsert_message_content race: message %s belongs to %s, not %s",
                            mid,
                            cross.conversation_id,
                            session_id,
                        )
                        return False
                    raise
                return await _update_existing(existing)

            auto_title = (
                _conversation_title_from_user_message(content) if role == "user" else ""
            )
            if auto_title and not (conversation.title or "").strip():
                conversation.title = auto_title
            await session.execute(
                text(
                    "UPDATE conversations SET message_count = message_count + 1, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = :cid"
                ),
                {"cid": session_id},
            )
            await session.commit()
            return True

    def _row_to_chat_message(
        self,
        role: str,
        content: str,
        tool_name: Optional[str],
        reasoning: Optional[str] = None,
    ) -> Optional[ChatMessage]:
        meta = {}
        if tool_name:
            meta["tool_name"] = tool_name
        # Reasoning is stored in DB for UI replay only — do not reinject into agent STM
        # (aligns with Open WebUI get_reasoning_format() -> None for OpenAI-compat).

        nr = normalize_message_role(role)
        if nr == "user":
            return ChatMessage.from_user(content, meta=meta)
        if nr == "assistant":
            return ChatMessage.from_assistant(content, meta=meta)
        if not is_model_context_role(nr):
            return None
        return None

    async def get_window(
        self,
        session_id: str,
        profile_name: str = "default",
        *,
        max_turns: int = 10,
        token_budget: Optional[int] = None,
        char_limit: int = 60000,
        exclude_message_ids: Optional[List[str]] = None,
    ) -> List[ChatMessage]:
        approx_rows = max(max_turns * 4, 32)
        async with get_async_session_maker()() as session:
            await self._ensure()
            q = select(
                Message.role, Message.content, Message.tool_name, Message.reasoning
            ).where(Message.conversation_id == session_id)
            if exclude_message_ids:
                q = q.where(Message.id.not_in(exclude_message_ids))
            q = q.order_by(Message.seq.desc()).limit(approx_rows)
            rows = list((await session.execute(q)).all())
        rows.reverse()
        parts: List[Tuple[str, str, Optional[str], Optional[str]]] = [
            (r[0], r[1], r[2], r[3]) for r in rows
        ]
        while parts:
            total_c = sum(len(p[1]) for p in parts)
            total_t = sum(_approx_tokens(p[1]) for p in parts)
            if total_c <= char_limit and (
                token_budget is None or total_t <= token_budget
            ):
                break
            parts.pop(0)
        out: List[ChatMessage] = []
        for r, c, t, rs in parts:
            msg = self._row_to_chat_message(r, c, t, rs)
            if msg is not None:
                out.append(msg)
        return out

    async def fts_search(
        self,
        query: str,
        *,
        limit: int = 20,
        session_id: Optional[str] = None,
        profile_name: Optional[str] = None,
        since_days: Optional[int] = 30,
    ) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        safe_q = re.sub(r'["\n\r]', " ", q)
        async with get_async_session_maker()() as session:
            await self._ensure()
            sql = """
                SELECT m.id, m.content, m.conversation_id AS session_id, m.profile_name AS profile_name,
                       m.role, m.created_at AS timestamp,
                       bm25(messages_fts) AS score
                FROM messages_fts
                JOIN messages m ON m.fts_rowid = messages_fts.rowid
                WHERE messages_fts MATCH :mq
            """
            params: Dict[str, Any] = {"mq": safe_q, "lim": limit}
            if session_id:
                sql += " AND m.conversation_id = :sid"
                params["sid"] = session_id
            if profile_name:
                sql += " AND m.profile_name = :pn"
                params["pn"] = profile_name
            if since_days is not None:
                sql += (
                    f" AND m.created_at >= datetime('now', '-{int(since_days)} days')"
                )
            sql += " ORDER BY score LIMIT :lim"
            try:
                res = await session.execute(text(sql), params)
                rows = res.mappings().all()
            except Exception as e:
                logger.debug("FTS bm25 failed, fallback: %s", e)
                sql_fb = """
                    SELECT m.id, m.content, m.conversation_id AS session_id, m.profile_name AS profile_name,
                           m.role, m.created_at AS timestamp
                    FROM messages_fts
                    JOIN messages m ON m.fts_rowid = messages_fts.rowid
                    WHERE messages_fts MATCH :mq
                """
                if session_id:
                    sql_fb += " AND m.conversation_id = :sid"
                if profile_name:
                    sql_fb += " AND m.profile_name = :pn"
                sql_fb += " LIMIT :lim"
                res = await session.execute(text(sql_fb), params)
                rows = res.mappings().all()
        return [dict(r) for r in rows]

    async def get_turn_context(
        self, message_id: str, window: int = 2
    ) -> List[Dict[str, Any]]:
        async with get_async_session_maker()() as session:
            await self._ensure()
            m0 = (
                await session.execute(select(Message).where(Message.id == message_id))
            ).scalar_one_or_none()
            if not m0:
                return []
            cid = m0.conversation_id
            q = (
                select(Message.id, Message.role, Message.content, Message.created_at)
                .where(Message.conversation_id == cid)
                .order_by(Message.seq)
                .limit(5000)
            )
            rows = (await session.execute(q)).all()
        ids = [r[0] for r in rows]
        if message_id not in ids:
            return []
        i = ids.index(message_id)
        lo = max(0, i - window)
        hi = min(len(rows), i + window + 1)
        out = []
        for r in rows[lo:hi]:
            out.append(
                {
                    "id": r[0],
                    "role": r[1],
                    "content": r[2],
                    "timestamp": r[3],
                }
            )
        return out

    async def fetch_unpromoted_rows(
        self, session_id: str, profile_name: str = "default", limit: int = 500
    ) -> List[Dict[str, Any]]:
        async with get_async_session_maker()() as session:
            await self._ensure()
            q = (
                select(
                    Message.id,
                    Message.role,
                    Message.content,
                    Message.tool_name,
                    Message.created_at,
                )
                .where(
                    Message.conversation_id == session_id,
                    Message.promoted_to_ltm == 0,
                )
                .order_by(Message.seq)
                .limit(limit)
            )
            rows = (await session.execute(q)).all()
        return [
            {
                "id": r[0],
                "role": r[1],
                "content": r[2],
                "tool_name": r[3],
                "timestamp": r[4],
            }
            for r in rows
        ]

    async def mark_promoted(self, message_ids: List[str]) -> None:
        if not message_ids:
            return
        async with get_async_session_maker()() as session:
            await self._ensure()
            await session.execute(
                update(Message)
                .where(Message.id.in_(message_ids))
                .values(promoted_to_ltm=1)
            )
            await session.commit()

    async def count_user_messages(
        self, session_id: str, profile_name: str = "default"
    ) -> int:
        async with get_async_session_maker()() as session:
            await self._ensure()
            q = (
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == session_id,
                    Message.role == "user",
                )
            )
            return int((await session.execute(q)).scalar_one() or 0)

    async def prune_old(
        self, session_id: str, profile_name: str = "default", keep_last_n: int = 50
    ) -> None:
        async with get_async_session_maker()() as session:
            await self._ensure()
            kept_rows = list(
                (
                    await session.execute(
                        text(
                            """
                            SELECT id FROM messages
                            WHERE conversation_id = :cid
                            ORDER BY seq DESC
                            LIMIT :k
                            """
                        ),
                        {"cid": session_id, "k": keep_last_n},
                    )
                ).all()
            )
            kept_ids = [r[0] for r in kept_rows]
            if not kept_ids:
                return
            all_ids = list(
                (
                    await session.execute(
                        select(Message.id).where(Message.conversation_id == session_id)
                    )
                )
                .scalars()
                .all()
            )
            pruned_ids = [mid for mid in all_ids if mid not in kept_ids]
            await _delete_messages_and_children(session, session_id, pruned_ids)
            await _cleanup_orphan_steps_and_attachments(session, session_id)
            await _recount_conversation_messages(session, session_id)
            await session.commit()

    async def fetch_messages_for_compaction(
        self,
        session_id: str,
        *,
        keep_last_n: int = 6,
    ) -> List[Dict[str, Any]]:
        """Messaggi da sintetizzare (tutto tranne gli ultimi keep_last_n per seq)."""
        from src.memory.context_compressor import (
            COMPACTION_MARKER,
            CONTEXT_SUMMARY_MARKER,
        )

        keep_last_n = max(1, int(keep_last_n))
        async with get_async_session_maker()() as session:
            await self._ensure()
            rows = list(
                (
                    await session.execute(
                        text(
                            """
                            SELECT role, content, tool_name, reasoning, timeline_json
                            FROM messages
                            WHERE conversation_id = :cid
                            AND id NOT IN (
                                SELECT id FROM (
                                    SELECT id FROM messages
                                    WHERE conversation_id = :cid2
                                    ORDER BY seq DESC
                                    LIMIT :k
                                )
                            )
                            ORDER BY seq ASC
                            """
                        ),
                        {"cid": session_id, "cid2": session_id, "k": keep_last_n},
                    )
                ).all()
            )
        out: List[Dict[str, Any]] = []
        for role, content, tool_name, reasoning, timeline_json in rows:
            body = content or ""
            if COMPACTION_MARKER in body or CONTEXT_SUMMARY_MARKER in body:
                continue
            out.append(
                {
                    "role": role,
                    "content": body,
                    "tool_name": tool_name,
                    "reasoning": reasoning,
                    "timeline_json": timeline_json,
                }
            )
        return out

    async def count_messages(self, session_id: str) -> int:
        async with get_async_session_maker()() as session:
            await self._ensure()
            q = (
                select(func.count())
                .select_from(Message)
                .where(Message.conversation_id == session_id)
            )
            return int((await session.execute(q)).scalar_one() or 0)

    async def persist_stm_compaction(
        self,
        session_id: str,
        *,
        profile_name: str = "default",
        summary_content: str,
        keep_last_n: int = 6,
    ) -> None:
        """Prune DB history to the STM tail and insert a compaction block before it."""
        from src.memory.context_compressor import (
            COMPACTION_MARKER,
            CONTEXT_SUMMARY_MARKER,
            append_last_assistant_to_compaction_block,
            format_compaction_block,
        )

        summary_content = (summary_content or "").strip()
        if not summary_content or keep_last_n < 1:
            return
        if (
            COMPACTION_MARKER not in summary_content
            and CONTEXT_SUMMARY_MARKER not in summary_content
        ):
            summary_content = format_compaction_block(
                summary_content, source_messages=0
            )
        async with get_async_session_maker()() as session:
            await self._ensure()
            kept_rows = list(
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, seq, content FROM messages
                            WHERE conversation_id = :cid
                            ORDER BY seq DESC
                            LIMIT :k
                            """
                        ),
                        {"cid": session_id, "k": keep_last_n},
                    )
                ).all()
            )
            if not kept_rows:
                return
            kept_ids = [r[0] for r in kept_rows]
            if any(
                COMPACTION_MARKER in (r[2] or "")
                or CONTEXT_SUMMARY_MARKER in (r[2] or "")
                for r in kept_rows
            ):
                all_ids = list(
                    (
                        await session.execute(
                            select(Message.id).where(
                                Message.conversation_id == session_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                pruned_ids = [mid for mid in all_ids if mid not in kept_ids]
                await _delete_messages_and_children(session, session_id, pruned_ids)
                await _cleanup_orphan_steps_and_attachments(session, session_id)
                await _sanitize_kept_assistant_timelines(session, session_id, kept_ids)
                await _recount_conversation_messages(session, session_id)
                await session.commit()
                return

            all_ids = list(
                (
                    await session.execute(
                        select(Message.id).where(Message.conversation_id == session_id)
                    )
                )
                .scalars()
                .all()
            )
            pruned_ids = [mid for mid in all_ids if mid not in kept_ids]
            last_assistant = await _fetch_last_significant_assistant_content(
                session, session_id, pruned_ids
            )
            if last_assistant:
                summary_content = append_last_assistant_to_compaction_block(
                    summary_content, last_assistant
                )

            min_seq = min(int(r[1]) for r in kept_rows)
            summary_seq = max(0, min_seq - 1)

            await _delete_messages_and_children(session, session_id, pruned_ids)
            await _cleanup_orphan_steps_and_attachments(session, session_id)
            await _sanitize_kept_assistant_timelines(session, session_id, kept_ids)

            await session.execute(
                text(
                    """
                    INSERT INTO messages (
                        id, conversation_id, tenant_id, seq, role, content,
                        tool_name, tool_call_id, profile_name, reasoning, timeline_json,
                        created_at, promoted_to_ltm
                    )
                    VALUES (
                        :id, :cid, :tid, :seq, 'user', :content,
                        NULL, NULL, :pname, NULL, NULL,
                        CURRENT_TIMESTAMP, 0
                    )
                    """
                ),
                {
                    "id": new_uuid7_str(),
                    "cid": session_id,
                    "tid": self.tenant_id,
                    "seq": summary_seq,
                    "content": summary_content,
                    "pname": profile_name,
                },
            )
            await _recount_conversation_messages(session, session_id)
            await session.commit()

    async def clear(self, session_id: str, profile_name: Optional[str] = None) -> None:
        async with get_async_session_maker()() as session:
            await self._ensure()
            if profile_name is None:
                await session.execute(
                    text("DELETE FROM messages WHERE conversation_id = :cid"),
                    {"cid": session_id},
                )
            else:
                await session.execute(
                    text(
                        "DELETE FROM messages WHERE conversation_id = :cid AND profile_name = :pf"
                    ),
                    {"cid": session_id, "pf": profile_name},
                )
            await session.commit()

    async def get_last_assistant_steps(self, session_id: str) -> List[Dict[str, Any]]:
        """Retrieves all steps executed during the last assistant turn in this session."""
        async with get_async_session_maker()() as session:
            await self._ensure()
            # Find the ID of the last assistant message
            last_msg_id = (
                await session.execute(
                    select(Message.id)
                    .where(
                        Message.conversation_id == session_id,
                        Message.role == "assistant",
                    )
                    .order_by(Message.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not last_msg_id:
                return []

            # Fetch steps associated with that message
            q = (
                select(
                    Step.name,
                    Step.type,
                    Step.input,
                    Step.output,
                    Step.is_error,
                    Step.metadata_json,
                )
                .where(
                    Step.conversation_id == session_id, Step.message_id == last_msg_id
                )
                .order_by(Step.created_at.asc())
            )
            rows = (await session.execute(q)).all()
            return [
                {
                    "name": r[0],
                    "type": r[1],
                    "input": r[2],
                    "output": r[3],
                    "is_error": bool(r[4]),
                    "metadata": r[5],
                }
                for r in rows
            ]

    async def add_step(
        self,
        session_id: str,
        name: str,
        type: str,
        input: Optional[str] = None,
        output: Optional[str] = None,
        is_error: bool = False,
        message_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        step_id: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> None:
        if not (message_id or "").strip():
            logger.warning(
                "add_step skipped: message_id required (session=%s name=%s)",
                session_id,
                name,
            )
            return
        async with get_async_session_maker()() as session:
            await self._ensure()
            from .ids import new_uuid7_str

            s = Step(
                id=step_id or new_uuid7_str(),
                conversation_id=session_id,
                tenant_id=self.tenant_id,
                message_id=message_id,
                parent_id=parent_id,
                name=name,
                type=type,
                input=input,
                output=output,
                is_error=1 if is_error else 0,
                metadata_json=metadata_json,
            )
            session.add(s)
            await session.commit()

    async def update_step(
        self,
        step_id: str,
        *,
        output: Optional[str] = None,
        is_error: Optional[bool] = None,
        input: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> None:
        async with get_async_session_maker()() as session:
            await self._ensure()
            from sqlalchemy import select

            from .models import Step

            row = (
                await session.execute(select(Step).where(Step.id == step_id))
            ).scalar_one_or_none()
            if not row:
                return
            if output is not None:
                row.output = output
            if input is not None:
                row.input = input
            if is_error is not None:
                row.is_error = 1 if is_error else 0
            if metadata_json is not None:
                row.metadata_json = metadata_json
            await session.commit()

    async def add_attachment(
        self,
        session_id: str,
        storage_key: str,
        original_name: str,
        mime: str,
        size_bytes: int,
        kind: str,
        message_id: Optional[str] = None,
        attachment_id: Optional[str] = None,
    ) -> None:
        async with get_async_session_maker()() as session:
            await self._ensure()
            from .ids import new_uuid7_str

            existing = (
                await session.execute(
                    select(Attachment.id).where(
                        Attachment.conversation_id == session_id,
                        Attachment.message_id == message_id,
                        Attachment.storage_key == storage_key,
                        Attachment.kind == kind,
                    )
                )
            ).first()
            if existing:
                return

            a = Attachment(
                id=attachment_id or new_uuid7_str(),
                conversation_id=session_id,
                tenant_id=self.tenant_id,
                message_id=message_id,
                storage_key=storage_key,
                original_name=original_name,
                mime=mime,
                size_bytes=size_bytes,
                kind=kind,
            )
            session.add(a)
            await session.commit()

    async def get_messages(
        self,
        session_id: str,
        profile_name: str = "default",
        limit: int = 20,
        char_limit: int = 60000,
    ) -> List[ChatMessage]:
        return await self.get_window(
            session_id, profile_name, max_turns=limit, char_limit=char_limit
        )
