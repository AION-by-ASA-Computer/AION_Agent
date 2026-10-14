"""Contesto della conversazione madre per i side thread.

Un side thread è una ``Conversation`` con ``parent_conversation_id`` valorizzato,
aperta da un passaggio (``anchor_json.quote``) di un messaggio assistant della
madre (``parent_message_id``). La sua finestra STM parte vuota: a ogni turno
``build_turn_context`` inietta questo blocco come layer ``side_thread_context``.
Il blocco non viene persistito né passato all'estrazione LTM.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger("aion.turn.side_thread")

_SOURCE_MAX_CHARS = 6000
_PRIOR_MAX_CHARS = 2400
_PRIOR_MESSAGES = 4


def _clip_around(text: str, needle: str, limit: int) -> str:
    """Tronca *text* a *limit* caratteri centrando la finestra su *needle*."""
    if len(text) <= limit:
        return text
    idx = text.find(needle) if needle else -1
    if idx < 0:
        return text[:limit].rstrip() + " …"
    half = max(0, (limit - len(needle)) // 2)
    lo = max(0, idx - half)
    hi = min(len(text), lo + limit)
    lo = max(0, hi - limit)
    return ("… " if lo > 0 else "") + text[lo:hi].strip() + (" …" if hi < len(text) else "")


def _clip_tail(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "… " + text[-limit:].lstrip()


def format_side_thread_context(
    *,
    parent_title: Optional[str],
    quote: str,
    source_message: str,
    prior_turns: List[Dict[str, str]],
) -> str:
    lines: List[str] = [
        "<side-thread-context>",
        "This conversation is a side thread: the user highlighted a passage of one of your "
        "answers in another conversation (the parent) and opened this thread to explore it. "
        "Answer in the context of the parent conversation and focus on the highlighted passage, "
        "unless the user steers elsewhere. Do not repeat the whole source answer.",
    ]
    if parent_title:
        lines.append(f"Parent conversation: {parent_title}")
    if prior_turns:
        lines.append("")
        lines.append("Parent conversation, turns before the source answer:")
        for t in prior_turns:
            lines.append(f"[{t['role']}] {t['content']}")
    lines += [
        "",
        "Source answer (yours, in the parent conversation):",
        source_message,
        "",
        "Highlighted passage:",
        f"«{quote}»",
        "</side-thread-context>",
    ]
    return "\n".join(lines)


async def build_side_thread_context(session_id: str, user_id: str) -> str:
    """Restituisce il blocco di contesto, o stringa vuota se *session_id* non è un side thread."""
    sid = (session_id or "").strip()
    if not sid:
        return ""
    from src.data.engine import get_async_session_maker
    from src.data.message_roles import normalize_message_role
    from src.data.models import Conversation, Message

    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, sid)
        if conv is None or not conv.parent_conversation_id:
            return ""
        parent = await session.get(Conversation, conv.parent_conversation_id)
        if parent is None or parent.user_id != conv.user_id:
            return ""
        try:
            anchor: Dict[str, Any] = json.loads(conv.anchor_json or "{}")
        except Exception:
            anchor = {}
        quote = str(anchor.get("quote") or "").strip()

        source_text = ""
        prior: List[Dict[str, str]] = []
        if conv.parent_message_id:
            src_row = (
                await session.execute(
                    select(Message.seq, Message.content).where(
                        Message.id == conv.parent_message_id,
                        Message.conversation_id == parent.id,
                    )
                )
            ).first()
            if src_row is not None:
                source_seq, source_text = src_row[0], src_row[1] or ""
                rows = (
                    await session.execute(
                        select(Message.role, Message.content)
                        .where(
                            Message.conversation_id == parent.id,
                            Message.seq < source_seq,
                            Message.archived_at.is_(None),
                        )
                        .order_by(Message.seq.desc())
                        .limit(_PRIOR_MESSAGES * 3)
                    )
                ).all()
                budget = _PRIOR_MAX_CHARS
                for role, content in rows:
                    nr = normalize_message_role(role)
                    body = (content or "").strip()
                    if nr not in ("user", "assistant") or not body:
                        continue
                    piece = _clip_tail(body, min(budget, 1200))
                    prior.append({"role": nr, "content": piece})
                    budget -= len(piece)
                    if len(prior) >= _PRIOR_MESSAGES or budget <= 200:
                        break
                prior.reverse()

    if not quote and not source_text:
        return ""
    return format_side_thread_context(
        parent_title=parent.title,
        quote=quote,
        source_message=_clip_around(source_text.strip(), quote, _SOURCE_MAX_CHARS)
        or "(source answer no longer available)",
        prior_turns=prior,
    )
