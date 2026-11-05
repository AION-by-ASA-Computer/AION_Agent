"""Turn plumbing shared by the messaging channels (WhatsApp, Telegram).

A chat started from a channel must be a real AION session, indistinguishable
from one started in chat-ui: a titled ``conversations`` row, every upload of the
session visible to the agent, the channel's thinking level mirrored into the
conversation metadata, and a live run that chat-ui can follow while the turn is
still streaming. These helpers implement that once, so the channels only deal
with their own transport (Meta Graph API, Telegram Bot API).

Used by ``src/channels/whatsapp/dispatcher.py`` and
``src/channels/telegram/adapter.py`` / ``chat.py``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from src.data.engine import get_async_session_maker
from src.data.models import Conversation
from src.session_workspace import is_user_facing_generated_file, session_root

logger = logging.getLogger("aion.channels.session_turn")

# Output folders scanned around a turn, and subtrees that never hold
# deliverables: artifact version history, offloaded tool results and the
# per-page text extracted by PDF auto-ingest.
_OUTPUT_ROOTS = ("workspace", "derived")
_SKIPPED_PREFIXES = (
    "workspace/.versions/",
    "derived/tool_results/",
    "derived/docs/",
)

OutputSnapshot = Dict[str, Tuple[int, int]]


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


def conversation_title(text: str) -> str:
    """Conversation title from the first message: one line, at most 60 chars."""
    title = " ".join((text or "").split())
    if len(title) > 60:
        title = title[:57].rstrip() + "…"
    return title


def session_attachments(
    conversation_id: str, turn_attachments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Every upload of the session, as chat-ui sends it in ``attachments``.

    The pipeline lists them to the agent split into "new this turn" (the ones
    in ``turn_attachments``) and "historical", so earlier photos/documents
    stay reachable in follow-up questions.
    """
    from src.session_workspace import list_dir

    turn_paths = {a.get("relative_path") for a in turn_attachments}
    historical = [
        {
            "relative_path": f["relative_path"],
            "original_name": f.get("name"),
            "mime": f.get("mime"),
        }
        for f in list_dir(conversation_id, "uploads")
        if f.get("relative_path") not in turn_paths
    ]
    return list(turn_attachments) + historical


# ---------------------------------------------------------------------------
# Thinking level
# ---------------------------------------------------------------------------


def resolve_channel_thinking(level: Optional[str]) -> str:
    """Turn-level reasoning (``off|min|medium|max``) for a channel turn.

    Mirrors what chat-ui sends (``thinking_enabled`` + ``reasoning_effort``)
    via ``resolve_turn_reasoning``, but the level comes from the channel config
    set in admin-ui instead of the user's composer:

    * ``off``                 → thinking disabled;
    * ``min|medium|max``      → thinking enabled at that effort (an explicit
      ``min`` is low-effort thinking, not "off", as in chat-ui);
    * unset (None/empty)      → system default (``AION_DEFAULT_REASONING_EFFORT`` /
      ``AION_THINKING_ENABLED``).
    """
    from src.runtime.reasoning_effort import resolve_turn_reasoning

    level = (level or "").strip().lower()
    if level == "off":
        return resolve_turn_reasoning(None, False)
    if level in ("min", "medium", "max"):
        return resolve_turn_reasoning(level, True)
    return resolve_turn_reasoning(None, None)


async def sync_thinking_metadata(
    conversation_id: str, level: str, *, channel: str = "channel"
) -> None:
    """Mirror the turn's thinking level into the conversation metadata.

    chat-ui restores its Thinking toggle/effort from ``metadata.thinking_enabled``
    / ``metadata.reasoning_effort`` when a conversation is opened and otherwise
    falls back to the browser's last-used value (usually "medium"). Writing the
    level used by the channel turn keeps the chat-ui composer consistent with
    what the channel actually ran. Called on every turn so a change made in
    admin-ui reaches already-open conversations too; best-effort (never blocks
    the reply). ``channel`` only labels the warning log.
    """
    try:
        async with get_async_session_maker()() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                return
            try:
                meta = json.loads(conv.metadata_json or "{}")
            except (TypeError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            patch: Dict[str, object] = {"thinking_enabled": level != "off"}
            # chat-ui's effort selector only knows min|medium|max: "off" keeps
            # the previous effort and only flips the toggle.
            if level != "off":
                patch["reasoning_effort"] = level
            if all(meta.get(k) == v for k, v in patch.items()):
                return
            meta.update(patch)
            conv.metadata_json = json.dumps(meta)
            await session.commit()
    except Exception:
        logger.warning("%s: thinking metadata sync failed", channel, exc_info=True)


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------


def snapshot_outputs(session_id: str) -> OutputSnapshot:
    """``{relative_path: (mtime_ns, size)}`` of the files in the output folders."""
    root = session_root(session_id)
    out: OutputSnapshot = {}
    for top in _OUTPUT_ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(_SKIPPED_PREFIXES):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            out[rel] = (st.st_mtime_ns, st.st_size)
    return out


def collect_new_outputs(before: OutputSnapshot, after: OutputSnapshot) -> List[str]:
    """Deliverables created or modified during the turn, oldest first."""
    changed = [
        rel
        for rel, stat in after.items()
        if before.get(rel) != stat and is_user_facing_generated_file(rel)
    ]
    return sorted(changed, key=lambda rel: (after[rel][0], rel))


# ---------------------------------------------------------------------------
# Live run visible to chat-ui
# ---------------------------------------------------------------------------


@dataclass
class LiveRun:
    """Handle of a channel turn registered as a chat-ui background run.

    ``user_message_id`` / ``assistant_message_id`` must be passed to
    ``AgentPipeline.run_stream`` so the persisted messages match the ids
    announced in redis (chat-ui uses them to attach to the stream).
    """

    conversation_id: str
    run: Any
    user_message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    assistant_message_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    async def publish(self, chunk: Dict[str, Any]) -> None:
        """Forward one pipeline chunk to the chat-ui clients following the turn."""
        event = {"event": "message", "data": json.dumps(chunk, default=str)}
        self.run.history.append(event)
        for q in list(self.run.queues):
            await q.put(event)


@contextlib.asynccontextmanager
async def background_run(
    conversation_id: str, *, profile: str
) -> AsyncIterator[LiveRun]:
    """Register the turn as ``_background_runs[conversation_id]`` while it runs.

    Same bookkeeping as ``POST /v1/chat/stream``: redis ``stream_active`` (so the
    chat-ui knows a turn is in progress when it opens the conversation) and a
    ``BackgroundChatRun`` that ``/v1/chat/stream/reconnect`` replays and follows.
    On exit (end of turn, timeout, error or cancellation) the run is closed and
    unregistered, so a dangling run never blocks the next one.
    """
    from src.api.v1.chat import BackgroundChatRun, _background_runs
    from src.runtime.redis_client import (
        redis_clear_stream_active,
        redis_set_stream_active,
    )

    run = BackgroundChatRun(conversation_id)
    live = LiveRun(conversation_id=conversation_id, run=run)
    await redis_set_stream_active(
        conversation_id,
        assistant_message_id=live.assistant_message_id,
        user_message_id=live.user_message_id,
        profile_name=profile,
    )
    _background_runs[conversation_id] = run
    try:
        yield live
    finally:
        run.is_done = True
        for q in list(run.queues):
            await q.put(None)
        # Only drop our own run: chat-ui may have replaced it meanwhile.
        if _background_runs.get(conversation_id) is run:
            _background_runs.pop(conversation_id, None)
        await redis_clear_stream_active(conversation_id)


__all__ = [
    "LiveRun",
    "OutputSnapshot",
    "background_run",
    "collect_new_outputs",
    "conversation_title",
    "resolve_channel_thinking",
    "session_attachments",
    "snapshot_outputs",
    "sync_thinking_metadata",
]
