import aiosqlite
import asyncio
import os
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from haystack.dataclasses import ChatMessage
from src.data.message_roles import is_model_context_role, normalize_message_role

""
logger = logging.getLogger("aion.history")


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ChatHistoryManager:
    def __init__(self, db_path: str = "data/chat_memory.db"):
        self.db_path = db_path
        self._unified = None
        self._unified_inited = False
        if os.getenv("AION_UNIFIED_DB", "1").lower() in ("1", "true", "yes"):
            from src.data.history_bridge import UnifiedHistoryBridge

            self._unified = UnifiedHistoryBridge()

    async def _init_unified_once(self) -> None:
        if not self._unified or self._unified_inited:
            return
        await self._unified.init()
        self._unified_inited = True

    async def _migrate_schema(self, db: aiosqlite.Connection) -> None:
        async with db.execute("PRAGMA table_info(messages)") as cursor:
            rows = await cursor.fetchall()
        cols = {row[1] for row in rows}
        alters: List[str] = []
        if "profile_name" not in cols:
            alters.append(
                "ALTER TABLE messages ADD COLUMN profile_name TEXT NOT NULL DEFAULT 'default'"
            )
        if "user_id" not in cols:
            alters.append("ALTER TABLE messages ADD COLUMN user_id TEXT")
        if "tool_name" not in cols:
            alters.append("ALTER TABLE messages ADD COLUMN tool_name TEXT")
        if "tool_call_id" not in cols:
            alters.append("ALTER TABLE messages ADD COLUMN tool_call_id TEXT")
        if "promoted_to_ltm" not in cols:
            alters.append(
                "ALTER TABLE messages ADD COLUMN promoted_to_ltm INTEGER NOT NULL DEFAULT 0"
            )
        for stmt in alters:
            await db.execute(stmt)
        if alters:
            await db.commit()
            logger.info("chat_memory.db schema migrated: %s", alters)

    async def _init_db(self):
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            # 1) Create full schema only when the DB is new (IF NOT EXISTS).
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL DEFAULT 'default',
                    user_id TEXT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_name TEXT,
                    tool_call_id TEXT,
                    promoted_to_ltm INTEGER NOT NULL DEFAULT 0,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.commit()

            # 2) Migrate legacy / partial schemas BEFORE indexes referencing new columns.
            await self._migrate_legacy_table(db)
            await self._migrate_schema(db)

            # 3) Indexes (safe only after profile_name & promoted_to_ltm exist).
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_profile ON messages(session_id, profile_name)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_not_promoted ON messages(promoted_to_ltm) "
                "WHERE promoted_to_ltm = 0"
            )
            await db.commit()

            await self._ensure_fts5(db)

    async def _ensure_fts5(self, db: aiosqlite.Connection) -> None:
        """FTS5 full-text su content (Hermes FASE D)."""
        try:
            await db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    content,
                    session_id UNINDEXED,
                    profile_name UNINDEXED,
                    role UNINDEXED,
                    timestamp UNINDEXED,
                    content='messages',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            await db.execute(
                """
                INSERT INTO messages_fts(rowid, content, session_id, profile_name, role, timestamp)
                SELECT m.id, m.content, m.session_id, m.profile_name, m.role, m.timestamp
                FROM messages m
                LEFT JOIN messages_fts f ON f.rowid = m.id
                WHERE f.rowid IS NULL
                """
            )
            await db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content, session_id, profile_name, role, timestamp)
                    VALUES (new.id, new.content, new.session_id, new.profile_name, new.role, new.timestamp);
                END
                """
            )
            await db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                END
                """
            )
            await db.execute(
                """
                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                    INSERT INTO messages_fts(rowid, content, session_id, profile_name, role, timestamp)
                    VALUES (new.id, new.content, new.session_id, new.profile_name, new.role, new.timestamp);
                END
                """
            )
            await db.commit()
        except Exception as e:
            logger.warning("FTS5 setup skipped or partial: %s", e)

    async def fts_search(
        self,
        query: str,
        *,
        limit: int = 20,
        session_id: Optional[str] = None,
        profile_name: Optional[str] = None,
        since_days: Optional[int] = 30,
    ) -> List[Dict[str, Any]]:
        """Ricerca FTS5 su messaggi storici."""
        if self._unified:
            await self._init_unified_once()
            return await self._unified.fts_search(
                query,
                limit=limit,
                session_id=session_id,
                profile_name=profile_name,
                since_days=since_days,
            )
        q = (query or "").strip()
        if not q:
            return []
        safe_q = re.sub(r'["\n\r]', " ", q)
        await self._init_db()
        where = ["messages_fts MATCH ?"]
        params: List[Any] = [safe_q]
        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        if profile_name:
            where.append("profile_name = ?")
            params.append(profile_name)
        if since_days is not None:
            where.append("timestamp >= datetime('now', ?)")
            params.append(f"-{int(since_days)} days")

        wh = " AND ".join(where)
        params_lim = params + [limit]

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            sql_bm25 = f"""
                SELECT rowid, content, session_id, profile_name, role, timestamp,
                       bm25(messages_fts) AS score
                FROM messages_fts
                WHERE {wh}
                ORDER BY score
                LIMIT ?
            """
            try:
                async with db.execute(sql_bm25, params_lim) as cur:
                    rows = await cur.fetchall()
            except Exception as e:
                logger.debug("FTS bm25 query fallback: %s", e)
                sql_fb = f"""
                    SELECT rowid, content, session_id, profile_name, role, timestamp
                    FROM messages_fts
                    WHERE {wh}
                    LIMIT ?
                """
                async with db.execute(sql_fb, params_lim) as cur:
                    rows = await cur.fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d.setdefault("rowid", d.get("rowid", d.get("id")))
            out.append(d)
        return out

    async def get_turn_context(
        self, message_id: Union[str, int], window: int = 2
    ) -> List[Dict[str, Any]]:
        """Messaggi nella stessa sessione attorno a message_id."""
        if self._unified:
            await self._init_unified_once()
            return await self._unified.get_turn_context(str(message_id), window)
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT session_id FROM messages WHERE id = ?", (message_id,)
            ) as cur:
                r = await cur.fetchone()
                if not r:
                    return []
                sid = r["session_id"]
            async with db.execute(
                """
                SELECT id, role, content, timestamp FROM messages
                WHERE session_id = ?
                ORDER BY id
                LIMIT 5000
                """,
                (sid,),
            ) as cur:
                rows = [dict(x) for x in await cur.fetchall()]
        ids = [row["id"] for row in rows]
        if message_id not in ids:
            return []
        i = ids.index(message_id)
        lo = max(0, i - window)
        hi = min(len(rows), i + window + 1)
        return rows[lo:hi]

    def fts_search_blocking(
        self,
        query: str,
        *,
        limit: int = 20,
        session_id: Optional[str] = None,
        profile_name: Optional[str] = None,
        since_days: Optional[int] = 30,
    ) -> List[Dict[str, Any]]:
        """Wrapper sync per tool MCP (nuovo event loop in thread se serve)."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.fts_search(
                    query,
                    limit=limit,
                    session_id=session_id,
                    profile_name=profile_name,
                    since_days=since_days,
                )
            )

        import concurrent.futures

        def _run():
            return asyncio.run(
                self.fts_search(
                    query,
                    limit=limit,
                    session_id=session_id,
                    profile_name=profile_name,
                    since_days=since_days,
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_run)
            return fut.result(timeout=120)

    def get_turn_context_blocking(
        self, message_id: Union[str, int], window: int = 2
    ) -> List[Dict[str, Any]]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.get_turn_context(message_id, window))

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(
                lambda: asyncio.run(self.get_turn_context(message_id, window))
            ).result(timeout=60)

    async def _migrate_legacy_table(self, db: aiosqlite.Connection) -> None:
        """If only legacy columns exist, copy into new table."""
        async with db.execute("PRAGMA table_info(messages)") as cursor:
            cols = {row[1] for row in await cursor.fetchall()}
        if "promoted_to_ltm" in cols:
            return
        if "profile_name" in cols:
            return
        if "role" not in cols:
            return
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                profile_name TEXT NOT NULL DEFAULT 'default',
                user_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                tool_call_id TEXT,
                promoted_to_ltm INTEGER NOT NULL DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        try:
            await db.execute(
                """
                INSERT INTO messages_new (session_id, profile_name, role, content, timestamp, promoted_to_ltm)
                SELECT session_id, 'default', role, content,
                       COALESCE(timestamp, CURRENT_TIMESTAMP), 0
                FROM messages
                """
            )
            await db.execute("DROP TABLE messages")
            await db.execute("ALTER TABLE messages_new RENAME TO messages")
            await db.commit()
            logger.info("chat_memory.db migrated from legacy schema")
        except Exception as e:
            logger.warning("Legacy migration skipped or failed: %s", e)
            await db.rollback()

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
    ):
        role = normalize_message_role(role)
        if self._unified:
            await self._init_unified_once()
            return await self._unified.add_message(
                session_id,
                role,
                content,
                profile_name=profile_name,
                user_id=user_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                reasoning=reasoning,
                message_id=message_id,
                timeline_json=timeline_json,
            )
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO messages (
                    session_id, profile_name, user_id, role, content, tool_name, tool_call_id, promoted_to_ltm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    session_id,
                    profile_name,
                    user_id,
                    role,
                    content,
                    tool_name,
                    tool_call_id,
                ),
            )
            await db.commit()

    async def update_message_timeline(
        self, message_id: str, timeline_json: str
    ) -> None:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.update_message_timeline(
                message_id, timeline_json
            )

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
        if self._unified:
            await self._init_unified_once()
            return await self._unified.upsert_message_content(
                session_id,
                message_id,
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
        return False

    async def get_last_assistant_steps(self, session_id: str) -> List[Dict[str, Any]]:
        """Bridge wrapper for get_last_assistant_steps."""
        if self._unified:
            await self._init_unified_once()
            return await self._unified.get_last_assistant_steps(session_id)

        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id FROM messages WHERE session_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return []
                last_msg_id = row[0]

            try:
                async with db.execute(
                    "SELECT name, type, input, output, is_error, metadata FROM steps WHERE conversation_id = ? AND message_id = ? ORDER BY id ASC",
                    (session_id, str(last_msg_id)),
                ) as cur:
                    return [dict(r) for r in await cur.fetchall()]
            except Exception:
                return []

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
    ):
        if self._unified:
            await self._init_unified_once()
            return await self._unified.add_step(
                session_id,
                name,
                type,
                input,
                output,
                is_error,
                message_id,
                parent_id,
                step_id,
                metadata_json=metadata_json,
            )
        # Non-unified implementation skipped for brevity as we focus on aion.db
        pass

    async def update_step(
        self,
        step_id: str,
        *,
        output: Optional[str] = None,
        is_error: Optional[bool] = None,
        input: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ):
        if self._unified:
            await self._init_unified_once()
            return await self._unified.update_step(
                step_id,
                output=output,
                is_error=is_error,
                input=input,
                metadata_json=metadata_json,
            )

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
    ):
        if self._unified:
            await self._init_unified_once()
            return await self._unified.add_attachment(
                session_id,
                storage_key,
                original_name,
                mime,
                size_bytes,
                kind,
                message_id,
                attachment_id,
            )
        # Non-unified implementation skipped
        pass

    async def get_messages(
        self,
        session_id: str,
        profile_name: str = "default",
        limit: int = 20,
        char_limit: int = 60000,
    ) -> List[ChatMessage]:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.get_messages(
                session_id, profile_name, limit=limit, char_limit=char_limit
            )
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT role, content, tool_name FROM messages
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (session_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()

        messages: List[ChatMessage] = []
        current_chars = 0
        for role, content, tool_name in rows:
            msg_len = len(content)
            if current_chars + msg_len > char_limit and len(messages) > 0:
                break
            mapped = self._row_to_chat_message(role, content, tool_name)
            if mapped is not None:
                messages.append(mapped)
                current_chars += msg_len
        messages.reverse()
        return messages

    def _row_to_chat_message(
        self, role: str, content: str, tool_name: Optional[str]
    ) -> Optional[ChatMessage]:
        nr = normalize_message_role(role)
        if nr == "user":
            return ChatMessage.from_user(content)
        if nr == "assistant":
            return ChatMessage.from_assistant(content)
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
    ) -> List[ChatMessage]:
        """Recent messages for the agent (chronological). Caps by approximate rows then char/token budget."""
        if self._unified:
            await self._init_unified_once()
            return await self._unified.get_window(
                session_id,
                profile_name,
                max_turns=max_turns,
                token_budget=token_budget,
                char_limit=char_limit,
            )
        await self._init_db()
        approx_rows = max(max_turns * 4, 32)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT role, content, tool_name FROM messages
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (session_id, approx_rows),
            ) as cursor:
                rows = await cursor.fetchall()
        rows.reverse()
        parts: List[Tuple[str, str, Optional[str]]] = [
            (role, content, tool_name) for role, content, tool_name in rows
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
        for r, c, t in parts:
            mapped = self._row_to_chat_message(r, c, t)
            if mapped is not None:
                out.append(mapped)
        return out

    async def count_user_messages(
        self, session_id: str, profile_name: str = "default"
    ) -> int:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.count_user_messages(session_id, profile_name)
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE session_id = ? AND role = 'user'
                """,
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
                return int(row[0]) if row else 0

    async def fetch_unpromoted_rows(
        self, session_id: str, profile_name: str = "default", limit: int = 500
    ) -> List[Dict[str, Any]]:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.fetch_unpromoted_rows(
                session_id, profile_name, limit
            )
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, role, content, tool_name, timestamp FROM messages
                WHERE session_id = ? AND promoted_to_ltm = 0
                ORDER BY id ASC LIMIT ?
                """,
                (session_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def mark_promoted(self, message_ids: List[Union[str, int]]) -> None:
        if not message_ids:
            return
        if self._unified:
            await self._init_unified_once()
            return await self._unified.mark_promoted([str(x) for x in message_ids])
        await self._init_db()
        placeholders = ",".join("?" * len(message_ids))
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"UPDATE messages SET promoted_to_ltm = 1 WHERE id IN ({placeholders})",
                message_ids,
            )
            await db.commit()

    async def fetch_messages_for_compaction(
        self,
        session_id: str,
        *,
        profile_name: str = "default",
        keep_last_n: int = 6,
    ) -> List[Dict[str, Any]]:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.fetch_messages_for_compaction(
                session_id, keep_last_n=keep_last_n
            )
        return []

    async def count_messages(
        self, session_id: str, profile_name: str = "default"
    ) -> int:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.count_messages(session_id)
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0] if row else 0)

    async def persist_stm_compaction(
        self,
        session_id: str,
        *,
        profile_name: str = "default",
        summary_content: str,
        keep_last_n: int = 6,
    ) -> None:
        if self._unified:
            await self._init_unified_once()
            await self._unified.persist_stm_compaction(
                session_id,
                profile_name=profile_name,
                summary_content=summary_content,
                keep_last_n=keep_last_n,
            )
            return

    async def prune_old(
        self, session_id: str, profile_name: str = "default", keep_last_n: int = 50
    ) -> None:
        if self._unified:
            await self._init_unified_once()
            return await self._unified.prune_old(session_id, profile_name, keep_last_n)
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f"""
                DELETE FROM messages WHERE session_id = ?
                AND id NOT IN (
                    SELECT id FROM messages WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                )
                """,
                (session_id, session_id, keep_last_n),
            )
            await db.commit()

    async def clear(self, session_id: str, profile_name: Optional[str] = None):
        if self._unified:
            await self._init_unified_once()
            return await self._unified.clear(session_id, profile_name)
        await self._init_db()
        async with aiosqlite.connect(self.db_path) as db:
            if profile_name is None:
                await db.execute(
                    "DELETE FROM messages WHERE session_id = ?", (session_id,)
                )
            else:
                await db.execute(
                    "DELETE FROM messages WHERE session_id = ? AND profile_name = ?",
                    (session_id, profile_name),
                )
            await db.commit()


history_manager = ChatHistoryManager()
