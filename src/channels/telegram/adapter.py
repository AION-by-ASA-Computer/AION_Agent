"""AionAdapter: unico punto di contatto del canale con il core AION.

Firma in docs/telegram/AION_MAP.md § 16. Il turno replica la preparazione di
``POST /v1/chat/stream`` (src/api/v1/chat.py) senza HTTP, come fa già
``src/runtime/cron_runner.py``: permessi su profilo e progetto, riga
``conversations`` con ``metadata.source = "telegram"``, impostazioni runtime
dell'utente, poi ``get_agent`` + ``AgentPipeline.run_stream``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Literal, Optional, Union

from src.data.engine import get_async_session_maker
from src.data.models import Conversation, User
from src.identity import sanitize_user_id

logger = logging.getLogger("aion.telegram")

SOURCE = "telegram"
_CANCELLED_MARK = "cancelled by user"


def default_tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


@dataclass(frozen=True)
class AionUserRef:
    """Le due identità AION, non intercambiabili (AION_MAP § 8)."""

    row_id: str  # users.id -> user_profile_access, FK tg_links
    identifier: str  # sanitize_user_id(users.identifier) -> agent user_id, conversations.user_id
    display_name: Optional[str] = None
    roles: tuple[str, ...] = ()
    tenant_id: str = "default"

    @property
    def label(self) -> str:
        return self.display_name or self.identifier


@dataclass(frozen=True)
class ProfileInfo:
    slug: str
    name: str
    description: str


@dataclass(frozen=True)
class ProjectInfo:
    slug: str
    display_name: str


# ---------- eventi del turno ----------
@dataclass(frozen=True)
class TextDelta:
    text: str
    kind: Literal["text"] = "text"


@dataclass(frozen=True)
class ReasoningDelta:
    text: str
    kind: Literal["reasoning"] = "reasoning"


@dataclass(frozen=True)
class ToolCall:
    name: str
    call_id: str = ""
    kind: Literal["tool_call"] = "tool_call"


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    call_id: str = ""
    kind: Literal["tool_result"] = "tool_result"


@dataclass(frozen=True)
class Final:
    text: str
    kind: Literal["final"] = "final"


@dataclass(frozen=True)
class Error:
    message: str
    cancelled: bool = False
    kind: Literal["error"] = "error"


ChatEvent = Union[TextDelta, ReasoningDelta, ToolCall, ToolResult, Final, Error]


class ChatAccessError(Exception):
    """Profilo o progetto non consentiti all'utente (messaggio già leggibile)."""


class ChannelPolicyError(ChatAccessError):
    """Profilo o progetto esclusi da Telegram dall'amministratore."""


def map_pipeline_chunk(chunk: dict) -> Optional[ChatEvent]:
    """Evento di ``AgentPipeline.run_stream`` → evento del canale (None = ignorato)."""
    ctype = chunk.get("type")
    if ctype == "token":
        content = chunk.get("content")
        return TextDelta(str(content)) if content else None
    if ctype == "reasoning":
        text = chunk.get("reasoning") or chunk.get("content")
        return ReasoningDelta(str(text)) if text else None
    if ctype == "tool_event":
        evt = chunk.get("event") or {}
        name = str(evt.get("name") or evt.get("tool_name") or "tool")
        call_id = str(evt.get("id") or evt.get("call_id") or "")
        etype = evt.get("type")
        if etype == "tool_start":
            return ToolCall(name, call_id=call_id)
        if etype in ("tool_end", "tool_error"):
            return ToolResult(name, ok=etype == "tool_end", call_id=call_id)
        return None
    if ctype == "final":
        return Final(str(chunk.get("text") or ""))
    if ctype == "error":
        msg = str(chunk.get("content") or chunk.get("error") or "error")
        return Error(msg, cancelled=_CANCELLED_MARK in msg.lower())
    return None


def _policy():
    from src.channels.telegram.config import get_telegram_settings

    return get_telegram_settings()


class AionAdapter:
    # ---------- identità ----------
    async def resolve_user(self, aion_user_row_id: str) -> Optional[AionUserRef]:
        async with get_async_session_maker()() as session:
            user = await session.get(User, aion_user_row_id)
        if user is None:
            return None
        from src.data.user_password import get_roles

        return AionUserRef(
            row_id=user.id,
            identifier=sanitize_user_id(user.identifier),
            display_name=(user.display_name or "").strip() or None,
            roles=tuple(get_roles(user)),
            tenant_id=user.tenant_id or default_tenant_id(),
        )

    # ---------- cataloghi ----------
    async def list_profiles(self, user: AionUserRef) -> list[ProfileInfo]:
        """Profili che l'utente può usare (``user_profile_access``; vuoto = tutti)."""
        from src.agent_profile import profile_manager
        from src.api.profile_access import allowed_profile_slugs

        allowed = set(await allowed_profile_slugs(user.row_id))
        out = [
            ProfileInfo(
                slug=p["slug"],
                name=p.get("name") or p["slug"],
                description=p.get("description") or "",
            )
            for p in profile_manager.list_profiles()
            if (not allowed or p["slug"] in allowed)
            and p["slug"].lower() not in _policy().blocked_profile_set
        ]
        return sorted(out, key=lambda p: p.name.lower())

    async def resolve_profile(self, user: AionUserRef, requested: Optional[str]) -> str:
        """Slug effettivo per l'utente: come ``enforce_profile_access`` ma senza HTTP."""
        from fastapi import HTTPException

        from src.agent_profile import ProfileNotFoundError, profile_manager
        from src.api.profile_access import enforce_profile_access

        name = (requested or "").strip() or "aion_std"
        try:
            name = profile_manager.resolve_profile(name).slug
        except ProfileNotFoundError:
            name = profile_manager.resolve_profile("aion_std").slug
        if name.lower() in _policy().blocked_profile_set:
            raise ChannelPolicyError(
                f"Il profilo «{name}» non è disponibile su Telegram (policy "
                "dell'amministratore)."
            )
        try:
            return await enforce_profile_access(user.row_id, name)
        except HTTPException as e:
            raise ChatAccessError(
                f"Il profilo «{name}» non è consentito al tuo utente. Scegline un altro con /profile."
            ) from e

    def profile_name(self, slug: str) -> str:
        from src.agent_profile import profile_manager

        p = profile_manager.get_profile(slug)
        return (getattr(p, "name", None) or slug) if p else slug

    async def list_projects(
        self, user: AionUserRef, profile_slug: Optional[str]
    ) -> list[ProjectInfo]:
        from src.memory.sql_query_memory.service import sql_query_memory

        try:
            rows = await sql_query_memory.list_projects(
                tenant_id=user.tenant_id,
                profile_slug=profile_slug,
                user_id=user.identifier,
            )
        except Exception as e:  # noqa: BLE001 — memoria SQL non configurata
            logger.warning("telegram: elenco progetti non disponibile: %s", e)
            return []
        blocked = _policy().blocked_project_set
        return [
            ProjectInfo(slug=r.slug, display_name=r.display_name or r.slug)
            for r in rows
            if r.slug.lower() not in blocked
        ]

    async def check_project(
        self, user: AionUserRef, project: str, profile_slug: str
    ) -> None:
        """Solleva ChatAccessError se l'utente non può usare il progetto."""
        if (project or "").strip().lower() in _policy().blocked_project_set:
            raise ChannelPolicyError(
                f"Il progetto «{project}» non è disponibile su Telegram (policy "
                "dell'amministratore)."
            )
        from src.runtime.query_memory_hooks import profile_has_memory_capability_by_slug
        from src.runtime.sql_query_project_scope import verify_user_project_access

        if not profile_has_memory_capability_by_slug(profile_slug):
            return
        err = await verify_user_project_access(
            project_slug=project,
            tenant_id=user.tenant_id,
            user_id=user.identifier,
            profile_slug=profile_slug,
        )
        if err:
            raise ChatAccessError(f"Progetto «{project}» non accessibile: {err}")

    # ---------- conversazioni ----------
    async def create_conversation(
        self,
        user: AionUserRef,
        *,
        profile_slug: str,
        project_slug: Optional[str],
        extra_metadata: Optional[dict] = None,
    ) -> str:
        from src.api.ownership import claim_session_owner_marker
        from src.data.ids import new_uuid7_str

        cid = new_uuid7_str()
        meta = {"source": SOURCE, "agent_mode": "normal", **(extra_metadata or {})}
        if project_slug:
            meta["sql_query_project"] = project_slug
        claim_session_owner_marker(cid, user.identifier)
        async with get_async_session_maker()() as session:
            session.add(
                Conversation(
                    id=cid,
                    tenant_id=user.tenant_id,
                    user_id=user.identifier,
                    profile_slug=profile_slug,
                    title=None,
                    message_count=0,
                    metadata_json=json.dumps(meta),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        return cid

    async def sync_conversation(
        self,
        user: AionUserRef,
        conversation_id: str,
        *,
        profile_slug: str,
        project_slug: Optional[str],
    ) -> bool:
        """Allinea profilo/progetto della conversazione; False se non è più utilizzabile
        (eliminata, archiviata o di un altro utente) e ne va aperta una nuova."""
        async with get_async_session_maker()() as session:
            row = await session.get(Conversation, conversation_id)
            if row is None or row.archived_at is not None:
                return False
            if sanitize_user_id(row.user_id) != user.identifier:
                return False
            meta = json.loads(row.metadata_json or "{}")
            changed = False
            if row.profile_slug != profile_slug:
                row.profile_slug = profile_slug
                changed = True
            if (meta.get("sql_query_project") or None) != (project_slug or None):
                if project_slug:
                    meta["sql_query_project"] = project_slug
                else:
                    meta.pop("sql_query_project", None)
                row.metadata_json = json.dumps(meta)
                changed = True
            if changed:
                row.updated_at = datetime.now(timezone.utc)
                await session.commit()
        return True

    # ---------- turno ----------
    async def default_llm_provider(self, tenant_id: str) -> Optional[str]:
        """Provider LLM che la Chat UI preseleziona: abilitato e ``is_default``.

        Senza ``llm_provider_name`` ``get_agent`` costruisce il generatore dalla
        configurazione ``.env``: stesso modello, ma parametri di generazione diversi
        da quelli del provider (budget di ragionamento, max_tokens, timeout).
        """
        from sqlalchemy import select

        from src.data.models import LlmProvider

        async with get_async_session_maker()() as session:
            slug = (
                await session.execute(
                    select(LlmProvider.slug)
                    .where(
                        LlmProvider.tenant_id == tenant_id,
                        LlmProvider.enabled.is_(True),
                        LlmProvider.is_default.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        return slug

    async def save_attachment(
        self, conversation_id: str, filename: str, data: bytes
    ) -> dict:
        """File ricevuto su Telegram → ``uploads/`` della conversazione, come
        l'upload della Chat UI (conversione Word e indicizzazione automatica)."""
        from src.session_workspace import save_upload
        from src.tools.doc_auto_ingest import schedule_auto_ingest
        from src.tools.office_auto_convert import apply_legacy_word_conversion

        meta = save_upload(conversation_id, filename, data)
        meta = await apply_legacy_word_conversion(conversation_id, meta)
        schedule_auto_ingest(conversation_id, meta)
        return meta

    async def chat_stream(
        self,
        user: AionUserRef,
        conversation_id: str,
        text: str,
        *,
        profile_slug: str,
        project_slug: Optional[str],
        attachments: Optional[list] = None,
        project_user: Optional[str] = None,
    ) -> AsyncIterator[ChatEvent]:
        """``project_user``: utente AION i cui permessi valgono per il progetto
        in questo turno (assistenti condivisi nei gruppi: il creatore)."""
        from src.agent_pipeline import AgentPipeline
        from src.main import get_agent, set_event_loop
        from src.runtime.reasoning_effort import resolve_turn_reasoning
        from src.runtime.redis_client import redis_clear_stream_cancel
        from src.runtime.runtime_settings import (
            profile_step_cap,
            resolve_turn_runtime_settings,
        )
        from src.settings import get_settings

        set_event_loop(asyncio.get_running_loop())
        # Un flag di stop rimasto da un turno precedente fermerebbe subito questo.
        await redis_clear_stream_cancel(conversation_id)
        llm_provider = await self.default_llm_provider(user.tenant_id)
        metadata: dict = {"source": SOURCE}
        if llm_provider:
            # Come /v1/chat/stream: la pipeline lo legge da qui.
            metadata["llm_provider_name"] = llm_provider

        agent, profile_name = await get_agent(
            profile_slug,
            session_id=conversation_id,
            user_id=user.identifier,
            tenant_id=user.tenant_id,
            agent_mode="normal",
            message_source="user_input",
            llm_provider_name=llm_provider,
        )
        pipeline = AgentPipeline(
            agent=agent,
            session_id=conversation_id,
            profile_name=profile_name,
            user_id=user.identifier,
            agent_mode="normal",
        )
        runtime = await resolve_turn_runtime_settings(
            None,
            user.identifier,
            profile_max_agent_steps=profile_step_cap(profile_name),
            context_window=get_settings().context_window,
        )
        from src.runtime.project_access_delegation import delegated

        with delegated(conversation_id, project_slug, project_user):
            async for chunk in pipeline.run_stream(
                text,
                reasoning_effort=resolve_turn_reasoning(None, None),
                message_source="user_input",
                attachments=attachments or None,
                turn_attachments=attachments or None,
                sql_query_project=project_slug,
                metadata=metadata,
                runtime=runtime,
            ):
                event = map_pipeline_chunk(chunk) if isinstance(chunk, dict) else None
                if event is not None:
                    yield event

    async def cancel(self, conversation_id: str) -> None:
        """La pipeline controlla il flag ogni ~0,5 s e chiude il turno."""
        from src.runtime.redis_client import redis_set_stream_cancel

        await redis_set_stream_cancel(conversation_id)
