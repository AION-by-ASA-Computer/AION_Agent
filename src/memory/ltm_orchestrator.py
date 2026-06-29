import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ..mcp_manager import mcp_manager
from ..skill_registry import skill_registry
from .llm_extract import complete_json_async
from .project_memory_scope import NAV_ROOMS, project_wing_prefix

logger = logging.getLogger("aion.memory.ltm")

_LTM_CTX_CHARS = int(os.getenv("AION_LTM_CONTEXT_MAX_CHARS", "4000"))
_WAKE_MAX_CHARS = int(os.getenv("AION_LTM_WAKE_MAX_CHARS", "1000"))
_LTM_ASST_CHARS = int(os.getenv("AION_LTM_EXTRACT_ASSISTANT_MAX_CHARS", "8000"))
_LTM_BATCH_CHARS = int(os.getenv("AION_LTM_BATCH_TRANSCRIPT_MAX_CHARS", "16000"))

_WING_ROOM_RE = re.compile(r"^[a-z0-9_\-]+$")
_LTM_MIN_IMPORTANCE = int(os.getenv("AION_LTM_MIN_IMPORTANCE", "2"))


def _is_project_wing(wing: str) -> bool:
    w = (wing or "").strip().lower()
    prefix = (project_wing_prefix() or "wing_proj_").strip().lower()
    if not prefix.endswith("_"):
        prefix = prefix.rstrip("_") + "_"
    return w.startswith(prefix) or w.startswith("wing_proj_")


def _filter_ltm_drawer(
    d: Dict[str, Any], default_wing: str
) -> Optional[Dict[str, Any]]:
    """Validate/normalize one drawer from LTM JSON (no user-text regex)."""
    wing = (d.get("wing") or default_wing).strip()
    room = (d.get("room") or "general").strip()
    content = (d.get("content") or "").strip()
    if len(content) < 10:
        return None
    try:
        imp = int(d.get("importance")) if d.get("importance") is not None else 3
    except (TypeError, ValueError):
        imp = 3
    if imp < _LTM_MIN_IMPORTANCE:
        logger.debug("LTM skip drawer low importance=%s wing=%s", imp, wing)
        return None
    if _is_project_wing(wing):
        raw_room = room.lower()
        if raw_room not in NAV_ROOMS:
            logger.warning(
                "LTM skip drawer: non-navigation room %s on project wing %s",
                raw_room,
                wing,
            )
            return None
        room = raw_room
    if not _WING_ROOM_RE.match(wing) or not _WING_ROOM_RE.match(room):
        logger.warning("LTM skip drawer invalid wing/room %s / %s", wing, room)
        return None
    if len(content) > 500:
        content = content[:497] + "..."
    return {"wing": wing, "room": room, "content": content}


def sanitize_id(part: str) -> str:
    s = re.sub(r"[^a-z0-9_\-]", "_", (part or "default").lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80] or "default"


def _tool_texts(result: Any) -> List[str]:
    if not hasattr(result, "content") or not result.content:
        return [str(result)]
    out = []
    for c in result.content:
        t = getattr(c, "text", None) or str(c)
        out.append(t)
    return out


async def _call_mcp_optional(
    chat_session_id: Optional[str], tool: str, arguments: Dict[str, Any]
) -> Optional[str]:
    try:
        return await _call_mcp(chat_session_id, tool, arguments)
    except Exception:
        return None


async def _call_mcp(
    chat_session_id: Optional[str], tool: str, arguments: Dict[str, Any]
) -> str:
    """
    Usa la stessa sessione MCP della chat quando `chat_session_id` è valorizzato (pool stdio).
    """
    async with mcp_manager.session_context(
        "mempalace", chat_session_id=chat_session_id
    ) as session:
        res = await session.call_tool(name=tool, arguments=arguments)
    return "\n".join(_tool_texts(res))


class LTMOrchestrator:
    """
    Long-term memory via MemPalace: wake-up, retrieval, extraction persist, optional diary.
    """

    def __init__(self, agent_name: Optional[str] = None):
        self.agent_name = agent_name or os.getenv("AION_LTM_AGENT_NAME", "AION")
        self._wake_by_session: Dict[str, Tuple[str, float]] = {}
        self.wake_ttl_sec = float(os.getenv("AION_LTM_WAKE_TTL", "300"))

    async def wake_up(self, chat_session_id: str) -> str:
        """
        Layered wake-up (MemPalace v3): prefer compact L0+L1 tools when available,
        else fall back to `mempalace_status` (truncated to AION_LTM_WAKE_MAX_CHARS).
        """
        now = time.time()
        prev = self._wake_by_session.get(chat_session_id)
        if prev and prev[0] and (now - prev[1]) < self.wake_ttl_sec:
            return prev[0]
        text = ""
        try:
            # v3-style compact tools (names may vary by MemPalace version)
            l0 = await _call_mcp_optional(chat_session_id, "mempalace_identity", {})
            l1 = await _call_mcp_optional(
                chat_session_id, "mempalace_top_drawers", {"limit": 8}
            )
            if l0 or l1:
                blob = json.dumps(
                    {"identity": (l0 or "").strip(), "top_drawers": (l1 or "").strip()},
                    ensure_ascii=False,
                )
                text = blob[:_WAKE_MAX_CHARS]
            else:
                full = await _call_mcp(chat_session_id, "mempalace_status", {})
                text = (full or "")[:_WAKE_MAX_CHARS]
            self._wake_by_session[chat_session_id] = (text, now)
            logger.info("MemPalace wake_up ok (%d chars)", len(text))
        except Exception as e:
            logger.warning("MemPalace wake_up failed: %s", e)
            self._wake_by_session[chat_session_id] = ("", now)
            return ""
        return text

    async def list_agents(self, chat_session_id: str) -> str:
        """MemPalace v3: `mempalace_list_agents` when available."""
        alt = await _call_mcp_optional(chat_session_id, "mempalace_list_agents", {})
        if alt is not None:
            return alt
        return (
            await _call_mcp_optional(chat_session_id, "mempalace_list_wings", {}) or ""
        )

    async def diary_write_for_agent(
        self,
        chat_session_id: str,
        agent_name: str,
        entry: str,
        topic: str = "aion",
    ) -> None:
        try:
            await _call_mcp(
                chat_session_id,
                "mempalace_diary_write",
                {
                    "agent_name": agent_name,
                    "entry": entry.strip()[:4000],
                    "topic": topic,
                },
            )
        except Exception as e:
            logger.warning("mempalace_diary_write (agent) failed: %s", e)

    async def precompact_flush(
        self,
        chat_session_id: str,
        user_id: str,
        head_transcript: str,
    ) -> None:
        """
        Hook before context compression: persist head messages as LTM batch + optional v3 flush tool.
        """
        await self.extract_and_persist(
            chat_session_id,
            user_id,
            head_transcript,
            "",
            mode="batch",
        )
        await _call_mcp_optional(
            chat_session_id,
            "mempalace_precompact_flush",
            {"transcript_excerpt": head_transcript[:8000]},
        )

    def user_wing(self, user_id: str) -> str:
        return f"wing_user_{sanitize_id(user_id)}"

    @staticmethod
    def is_small_talk(text: str) -> bool:
        """Heuristic to detect if a query is likely small talk or doesn't need historical context."""
        clean = text.lower().strip().strip("?!.")
        if len(clean) < 3:
            return True
        # Common Italian and English small talk patterns
        tokens = clean.split()
        if len(tokens) <= 3:
            stops = {
                "ciao",
                "buongiorno",
                "buonasera",
                "ehi",
                "hey",
                "salve",
                "grazie",
                "ottimo",
                "perfetto",
                "ok",
                "bene",
                "male",
                "stai",
                "va",
                "fai",
                "chi",
                "sei",
                "cosa",
                "fai",
                "hello",
                "hi",
                "thanks",
                "thank",
                "good",
                "bad",
                "well",
                "how",
                "are",
                "you",
                "doing",
                "today",
                "help",
                "me",
            }
            if all(t in stops for t in tokens):
                return True
        return False

    async def retrieve_context(
        self, user_input: str, user_id: str, chat_session_id: str
    ) -> str:
        if os.getenv("AION_LTM_RETRIEVAL", "1").lower() in ("0", "false", "no"):
            return ""

        # SKIP retrieval for small talk to avoid context pollution
        if self.is_small_talk(user_input):
            logger.debug("LTM: skipping retrieval for small talk: %s", user_input)
            return ""

        wing_u = self.user_wing(user_id)
        wing_ctx = "wing_session_context"
        limit = int(os.getenv("AION_LTM_SEARCH_LIMIT", "5"))
        chunks: List[str] = []
        try:
            for wing in (wing_u, wing_ctx):
                q = await _call_mcp(
                    chat_session_id,
                    "mempalace_search",
                    {"query": user_input, "wing": wing, "limit": limit},
                )
                if q and q.strip():
                    # Formato più naturale senza nomi tecnici delle wing
                    chunks.append(f"--- INFO DI SISTEMA / UTENTE ---\n{q}")
        except Exception as e:
            logger.warning("mempalace_search failed: %s", e)

        for entity in self._entity_hints(user_input)[:5]:
            try:
                kg = await _call_mcp(
                    chat_session_id, "mempalace_kg_query", {"entity": entity}
                )
                if kg and kg.strip():
                    chunks.append(f"### KG entity `{entity}`\n{kg}")
            except Exception:
                try:
                    kg = await _call_mcp(
                        chat_session_id,
                        "mempalace_kg_query",
                        {"subject": entity},
                    )
                    if kg and kg.strip():
                        chunks.append(f"### KG subject `{entity}`\n{kg}")
                except Exception as e2:
                    logger.debug("kg_query skip %s: %s", entity, e2)

        if not chunks:
            return ""

        # Optional: Secondary filter to ensure at least one keyword overlap if query is short
        final_chunks = []
        query_words = set(
            re.findall(r"\w{4,}", user_input.lower())
        )  # Solo parole lunghe (keywords)

        for c in chunks:
            if not query_words:  # Se la query è troppo corta o generica, fidati della ricerca (ma is_small_talk ha già filtrato i saluti)
                final_chunks.append(c)
                continue

            content_lower = c.lower()
            if any(w in content_lower for w in query_words):
                final_chunks.append(c)
            else:
                logger.debug(
                    "LTM: filtering out potentially irrelevant chunk (no keyword overlap)"
                )

        if not final_chunks:
            return ""

        return "## Contesto e Conoscenza Rilevante\n" + "\n\n".join(final_chunks)

    @staticmethod
    def _entity_hints(text: str) -> List[str]:
        seen = set()
        out: List[str] = []
        for m in re.finditer(
            r"\b[a-zA-Z][-a-zA-Z0-9]*(?:\.[a-zA-Z][-a-zA-Z0-9]*)+\b", text
        ):
            host = m.group(0)
            if host not in seen:
                seen.add(host)
                out.append(host)
        for m in re.finditer(r"\b[A-Z][A-Z0-9_]{2,}\b", text):
            tok = m.group(0)
            if tok not in seen and len(tok) <= 32:
                seen.add(tok)
                out.append(tok)
        return out

    def _extraction_skill_text(self) -> str:
        return skill_registry.get_skill("ltm_extraction") or ""

    async def extract_and_persist(
        self,
        session_id: str,
        user_id: str,
        user_input: str,
        assistant_output: str,
        *,
        mode: str = "turn",
        active_project: Optional[str] = None,
        profile_slug: Optional[str] = None,
    ) -> None:
        if os.getenv("AION_LTM_EXTRACT", "1").lower() in ("0", "false", "no"):
            return
        system = self._extraction_skill_text()
        if not system:
            system = "Rispondi solo con JSON valido secondo lo schema LTM."
        ctx_prefix = ""
        if active_project:
            from .project_memory_scope import project_context_block_async

            ctx_prefix = (
                await project_context_block_async(
                    active_project, profile_slug=profile_slug
                )
                + "\n\n"
            )

        batch_note = ""
        if mode == "batch":
            batch_note = (
                "\nModalità: consolidamento batch — sintetizza senza duplicare.\n"
            )
            user_prompt = (
                ctx_prefix
                + batch_note
                + "TRANSCRIPT:\n"
                + user_input[:_LTM_BATCH_CHARS]
            )
        else:
            user_prompt = ctx_prefix + (
                "USER_INPUT:\n"
                + user_input[:_LTM_CTX_CHARS]
                + "\n\nASSISTANT_OUTPUT:\n"
                + assistant_output[:_LTM_ASST_CHARS]
            )
        try:
            data = await complete_json_async(system, user_prompt)
        except Exception as e:
            logger.warning("LTM extraction LLM failed: %s", e)
            return
        await self._apply_persist(session_id, user_id, data)

    async def _apply_persist(
        self, session_id: str, user_id: str, data: Dict[str, Any]
    ) -> None:
        if not data.get("should_persist"):
            return
        default_wing = self.user_wing(user_id)
        drawers = data.get("drawers") or []
        for d in drawers:
            if not isinstance(d, dict):
                continue
            normalized = _filter_ltm_drawer(d, default_wing)
            if not normalized:
                continue
            try:
                await _call_mcp(
                    session_id,
                    "mempalace_add_drawer",
                    normalized,
                )
            except Exception as e:
                logger.warning("mempalace_add_drawer failed: %s", e)

        for t in data.get("kg_triples") or []:
            if not isinstance(t, dict):
                continue
            sub, pred, obj = t.get("subject"), t.get("predicate"), t.get("object")
            if not all(isinstance(x, str) and x.strip() for x in (sub, pred, obj)):
                continue
            args = {
                "subject": sub.strip(),
                "predicate": pred.strip(),
                "object": obj.strip(),
            }
            vf = t.get("valid_from")
            if vf:
                args["valid_from"] = vf
            try:
                await _call_mcp(session_id, "mempalace_kg_add", args)
            except Exception as e:
                logger.warning("mempalace_kg_add failed: %s", e)

        for inv in data.get("kg_invalidations") or []:
            if not isinstance(inv, dict):
                continue
            sub, pred, obj = inv.get("subject"), inv.get("predicate"), inv.get("object")
            if not all(isinstance(x, str) and x.strip() for x in (sub, pred, obj)):
                continue
            try:
                await _call_mcp(
                    session_id,
                    "mempalace_kg_invalidate",
                    {
                        "subject": sub.strip(),
                        "predicate": pred.strip(),
                        "object": obj.strip(),
                    },
                )
            except Exception as e:
                logger.warning("mempalace_kg_invalidate failed: %s", e)

        diary = data.get("diary_entry")
        if isinstance(diary, str) and diary.strip():
            try:
                await _call_mcp(
                    session_id,
                    "mempalace_diary_write",
                    {
                        "agent_name": self.agent_name,
                        "entry": diary.strip()[:4000],
                        "topic": "aion_ltm",
                    },
                )
            except Exception as e:
                logger.warning("mempalace_diary_write failed: %s", e)

    @staticmethod
    def _format_wake_summary(wake_raw: str, max_plain: int = 1800) -> str:
        """Compact memory status overview for the agent."""
        if not (wake_raw or "").strip():
            return ""
        try:
            data = json.loads(wake_raw)
        except (json.JSONDecodeError, TypeError):
            # Fallback if it's already a string (e.g. legacy mempalace_status)
            txt = (wake_raw or "").strip()
            if "total_drawers" in txt:
                return ""
            return txt[:max_plain]

        if not isinstance(data, dict):
            return str(wake_raw)[:max_plain]

        identity = data.get("identity", "").strip()
        if identity:
            return f"Identity/preferences: {identity}"

        if data.get("total_drawers"):
            return ""

        return ""

    def build_augmented_user_text(
        self, user_input: str, ltm_context: str, wake_raw: str
    ) -> str:
        """
        Build the current user message: optional identity summary + raw request.
        Autonomous mode: ltm_context is now ignored by default (agent uses tools instead).
        """
        if os.getenv("AION_LTM_PREFIX_IN_USER", "1").lower() in ("0", "false", "no"):
            return user_input

        blocks: List[str] = []
        wake_short = self._format_wake_summary(wake_raw)
        if wake_short:
            blocks.append(f"[session_memory: {wake_short}]")

        if not blocks:
            return user_input

        return "\n".join(blocks) + "\n" + user_input


ltm_orchestrator = LTMOrchestrator()
