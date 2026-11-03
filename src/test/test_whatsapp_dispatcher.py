"""Dispatcher: collegamento, comandi, turno dell'agente, risposte, ripresa."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, update

from src.test.whatsapp_test_helpers import (
    DISPLAY_PHONE,
    TENANT,
    FakeGraph,
    configure_channel,
    load_fixture,
)

BSUID = "IT.1111111111111111"
_N = {"n": 0}


@pytest.fixture
def graph(monkeypatch):
    from src.channels.whatsapp import dispatcher

    fake = FakeGraph()
    monkeypatch.setattr(dispatcher, "graph_client_factory", fake.factory)
    return fake


@pytest.fixture
def turns(monkeypatch):
    """Sostituisce ``run_turn``: restituisce ``turns.reply`` e registra le chiamate."""
    from src.channels.whatsapp import dispatcher

    class _Turns:
        calls: list = []
        reply = dispatcher.TurnResult(
            conversation_id="conv-1", text="**Ieri 12 ordini**"
        )
        raise_exc = None
        delay = 0.0  # simulated turn duration (seconds)

    state = _Turns()
    state.calls = []

    async def fake_run_turn(**kwargs):
        state.calls.append(kwargs)
        if state.delay:
            await asyncio.sleep(state.delay)
        if state.raise_exc:
            raise state.raise_exc
        return state.reply

    monkeypatch.setattr(dispatcher, "run_turn", fake_run_turn)
    return state


def _msg(text="Quanti ordini ieri?", *, fixture="text_with_phone", **changes):
    from src.channels.whatsapp.payload import parse_webhook

    (msg,) = parse_webhook(load_fixture(fixture)).messages
    _N["n"] += 1
    fields = {"wamid": f"wamid.T{_N['n']}"}
    if fixture == "text_with_phone":
        fields["text"] = text
    fields.update(changes)
    return replace(msg, **fields)


async def _deliver(msg):
    from src.channels.whatsapp import dispatcher, store

    assert await store.insert_inbound(TENANT, msg)
    await dispatcher.process(TENANT, msg.wamid)
    return await _row(msg.wamid)


async def _row(wamid):
    from src.data.engine import get_async_session_maker
    from src.data.models import WhatsAppMessage

    async with get_async_session_maker()() as session:
        return await session.get(WhatsAppMessage, wamid)


async def _link(user_id="u1"):
    from src.channels.whatsapp import linking

    code = (await linking.create_link_code(TENANT, user_id, DISPLAY_PHONE)).code
    res = await linking.consume_code(
        TENANT, code=code, bsuid=BSUID, phone="393331112233", profile_name="Mario"
    )
    assert res.ok
    return await linking.get_identity(TENANT, BSUID)


@pytest.mark.anyio
async def test_unknown_sender_gets_settings_link_once(wa_db, graph, turns):
    await configure_channel()

    row = await _deliver(_msg("ciao"))
    assert row.status == "done" and row.payload_json is None
    await _deliver(_msg("c'è qualcuno?"))

    assert len(graph.sent) == 1
    body = graph.sent[0]["body"]
    assert "https://aion.example.com/settings?tab=whatsapp" in body
    assert graph.sent[0]["to"] == "393331112233"
    assert graph.sent[0]["recipient"] == BSUID
    assert turns.calls == []


@pytest.mark.anyio
async def test_link_command_links_and_welcomes(wa_db, graph, turns):
    await configure_channel()
    from src.channels.whatsapp import linking

    code = (await linking.create_link_code(TENANT, "u1", DISPLAY_PHONE)).code
    await _deliver(_msg(f"COLLEGA {code}"))

    ident = await linking.get_identity(TENANT, BSUID)
    assert ident is not None and ident.user_id == "u1"
    (welcome,) = graph.bodies
    assert welcome.startswith("Ciao Mario Rossi!")
    assert "/nuova" in welcome

    await _deliver(_msg("COLLEGA ZZZZZZZZ"))
    assert "Codice non valido" in graph.bodies[-1]


@pytest.mark.anyio
async def test_bsuid_only_sender_reply_uses_recipient(wa_db, graph, turns):
    await configure_channel()
    await _deliver(_msg(fixture="text_bsuid_only"))
    (sent,) = graph.sent
    assert sent["to"] is None and sent["recipient"] == "IT.2222222222222222"


@pytest.mark.anyio
async def test_linked_turn_sends_formatted_reply(wa_db, graph, turns):
    await configure_channel()
    await _link()

    msg = _msg("Quanti ordini ieri?")
    row = await _deliver(msg)

    assert graph.typing == [msg.wamid]
    assert graph.bodies == ["*Ieri 12 ordini*"]
    (call,) = turns.calls
    assert call["text"] == "Quanti ordini ieri?"
    assert call["user"].id == "u1"
    assert row.status == "done" and row.conversation_id == "conv-1"

    out = await _row("wamid.OUT1")
    assert out.direction == "out" and out.conversation_id == "conv-1"

    from src.channels.whatsapp import linking

    ident = await linking.get_identity(TENANT, BSUID)
    assert ident.last_inbound_at is not None
    assert ident.wa_profile_name == "Mario Rossi"


@pytest.fixture
def fast_typing(monkeypatch):
    """Shrink the keep-alive timings so a long turn lasts a fraction of a second."""
    from src.channels.whatsapp import dispatcher

    monkeypatch.setattr(dispatcher, "TYPING_REFRESH_S", 0.02)
    monkeypatch.setenv("AION_WHATSAPP_WORKING_NOTICE_S", "0.05")


@pytest.mark.anyio
async def test_long_turn_keeps_typing_and_sends_working_notice(
    wa_db, graph, turns, fast_typing
):
    """A turn longer than Meta's 25 s window: the indicator is refreshed, the
    "ci sto lavorando" notice goes out once before the reply, and the
    keep-alive stops with the turn."""
    from src.channels.whatsapp.dispatcher import MESSAGES

    await configure_channel()
    await _link()
    turns.delay = 0.2

    msg = _msg("analisi lunga")
    await _deliver(msg)

    assert len(graph.typing) >= 3 and set(graph.typing) == {msg.wamid}
    assert graph.bodies == [MESSAGES["working"], "*Ieri 12 ordini*"]
    # The notice hides the indicator: it is re-sent right after it.
    refreshes = len(graph.typing)
    await asyncio.sleep(0.1)
    assert len(graph.typing) == refreshes


@pytest.mark.anyio
async def test_working_notice_disabled(wa_db, graph, turns, fast_typing, monkeypatch):
    """``AION_WHATSAPP_WORKING_NOTICE_S=0``: keep-alive only, no notice."""
    monkeypatch.setenv("AION_WHATSAPP_WORKING_NOTICE_S", "0")
    await configure_channel()
    await _link()
    turns.delay = 0.1

    await _deliver(_msg("analisi lunga"))

    assert len(graph.typing) > 1
    assert graph.bodies == ["*Ieri 12 ordini*"]


@pytest.mark.anyio
async def test_typing_keepalive_gives_up_after_failures(
    wa_db, graph, turns, fast_typing, monkeypatch
):
    """Meta rejecting the indicator: refreshes stop after ``TYPING_MAX_FAILURES``
    in a row, and the turn still gets its reply."""
    from src.channels.whatsapp import dispatcher
    from src.channels.whatsapp.graph_client import GraphError

    monkeypatch.setenv("AION_WHATSAPP_WORKING_NOTICE_S", "0")
    await configure_channel()
    await _link()
    graph.typing_error = GraphError("message too old")
    turns.delay = 0.3

    await _deliver(_msg("analisi lunga"))

    # Initial indicator + the failed refreshes, then nothing more.
    assert len(graph.typing) == 1 + dispatcher.TYPING_MAX_FAILURES
    assert graph.bodies == ["*Ieri 12 ordini*"]


@pytest.mark.anyio
async def test_rejected_typing_sends_working_notice_early(
    wa_db, graph, turns, fast_typing, monkeypatch
):
    """Meta rejecting a refresh: the notice goes out right away (once), without
    waiting for ``AION_WHATSAPP_WORKING_NOTICE_S``."""
    from src.channels.whatsapp.dispatcher import MESSAGES
    from src.channels.whatsapp.graph_client import GraphError

    monkeypatch.setenv("AION_WHATSAPP_WORKING_NOTICE_S", "60")
    await configure_channel()
    await _link()
    graph.typing_error = GraphError("message too old")
    turns.delay = 0.15

    await _deliver(_msg("analisi lunga"))

    assert graph.bodies == [MESSAGES["working"], "*Ieri 12 ordini*"]


@pytest.mark.anyio
async def test_typing_keepalive_stops_on_turn_exception(
    wa_db, graph, turns, fast_typing
):
    """A turn that crashes mid-way does not leave the keep-alive running."""
    await configure_channel()
    await _link()
    turns.delay = 0.03
    turns.raise_exc = RuntimeError("boom")

    row = await _deliver(_msg("rompi tutto"))

    assert row.status == "failed"
    refreshes = len(graph.typing)
    await asyncio.sleep(0.1)
    assert len(graph.typing) == refreshes


@pytest.mark.anyio
async def test_long_reply_is_split_and_truncated(wa_db, graph, turns, monkeypatch):
    from src.channels.whatsapp import dispatcher

    monkeypatch.setenv("AION_WHATSAPP_MAX_CHUNKS", "2")
    await configure_channel()
    await _link()
    para = "parola " * 500  # ~3500 caratteri
    turns.reply = dispatcher.TurnResult(
        conversation_id="conv-9", text="\n\n".join([para] * 4)
    )

    await _deliver(_msg("riassumi"))

    assert len(graph.sent) == 2
    assert all(len(b) <= 4096 for b in graph.bodies)
    assert graph.bodies[-1].endswith(
        "Continua su AION: https://aion.example.com/c/conv-9"
    )


@pytest.mark.anyio
async def test_commands(wa_db, graph, turns):
    await configure_channel()
    ident = await _link()
    from src.channels.whatsapp import linking

    await linking.update_identity(ident.id, active_conversation_id="conv-old")

    await _deliver(_msg("/aiuto"))
    assert "*AION su WhatsApp*" in graph.bodies[-1]

    await _deliver(_msg("/nuova"))
    assert graph.bodies[-1].startswith("Ok, nuova conversazione")
    assert (await linking.get_identity(TENANT, BSUID)).active_conversation_id is None

    await _deliver(_msg("/scollega"))
    assert "scollegato" in graph.bodies[-1]
    assert await linking.get_identity(TENANT, BSUID) is None
    assert turns.calls == []


@pytest.mark.anyio
async def test_non_text_message(wa_db, graph, turns):
    """Videos are declined politely; reactions get no answer at all."""
    from src.channels.whatsapp.dispatcher import MESSAGES

    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="audio_voice", type="video"))
    assert graph.bodies == [MESSAGES["media_unsupported"]]
    await _deliver(_msg(fixture="audio_voice", type="reaction", media=None))
    assert len(graph.bodies) == 1
    assert turns.calls == []


@pytest.mark.anyio
async def test_media_disabled_falls_back_to_text_only(wa_db, graph, turns, monkeypatch):
    """``AION_WHATSAPP_MEDIA=0`` restores the phase-1 "text only" behaviour."""
    from src.channels.whatsapp.dispatcher import MESSAGES

    monkeypatch.setenv("AION_WHATSAPP_MEDIA", "0")
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="image_no_caption"))
    assert graph.bodies == [MESSAGES["text_only"]]
    assert graph.downloaded == [] and turns.calls == []


@pytest.mark.anyio
async def test_timeout_reply(wa_db, graph, turns):
    from src.channels.whatsapp import dispatcher

    await configure_channel()
    await _link()
    turns.reply = dispatcher.TurnResult(conversation_id="conv-2", timed_out=True)
    await _deliver(_msg("domanda lenta"))
    assert graph.bodies[-1].endswith("https://aion.example.com/c/conv-2")


@pytest.mark.anyio
async def test_turn_exception_marks_failed_and_apologizes(wa_db, graph, turns):
    from src.channels.whatsapp import config_service

    await configure_channel()
    await _link()
    turns.raise_exc = RuntimeError("boom")

    row = await _deliver(_msg("rompi tutto"))

    assert row.status == "failed" and row.error_code == "RuntimeError"
    assert graph.bodies[-1].startswith("Si è verificato un errore")
    config_service.invalidate_cache()
    assert "boom" in (await config_service.get_channel(TENANT)).last_error


@pytest.mark.anyio
async def test_disabled_channel_skips(wa_db, graph, turns):
    from src.channels.whatsapp import config_service

    await configure_channel()
    await _link()
    await config_service.set_enabled(TENANT, False)
    row = await _deliver(_msg("ciao"))
    assert row.status == "done"
    assert graph.sent == [] and turns.calls == []


@pytest.mark.anyio
async def test_number_change_system_message(wa_db, graph, turns):
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="number_change"))
    from src.channels.whatsapp import linking

    assert (await linking.get_identity(TENANT, BSUID)).phone_e164 == "393339998877"
    assert graph.sent == []


@pytest.mark.anyio
async def test_deleted_user_is_unlinked(wa_db, graph, turns):
    await configure_channel()
    await _link("u2")
    from src.data.engine import get_async_session_maker
    from src.data.models import User

    # Utente cancellato: il collegamento sparisce (FK con cascade).
    async with get_async_session_maker()() as session:
        await session.execute(delete(User).where(User.id == "u2"))
        await session.commit()

    await _deliver(_msg("ciao"))
    from src.channels.whatsapp import linking

    assert await linking.get_identity(TENANT, BSUID) is None
    assert "settings?tab=whatsapp" in graph.bodies[-1]
    assert turns.calls == []


@pytest.mark.anyio
async def test_already_processed_is_skipped(wa_db, graph, turns):
    from src.channels.whatsapp import dispatcher, store

    await configure_channel()
    msg = _msg("ciao")
    await _deliver(msg)
    await dispatcher.process(TENANT, msg.wamid)
    await store.set_inbound_status(msg.wamid, "failed")
    await dispatcher.process(TENANT, msg.wamid)
    assert len(graph.sent) == 1


@pytest.mark.anyio
async def test_resume_pending(wa_db, monkeypatch):
    from src.channels.whatsapp import dispatcher, store
    from src.data.engine import get_async_session_maker
    from src.data.models import WhatsAppMessage

    await configure_channel()
    recent, old = _msg("a"), _msg("b")
    assert await store.insert_inbound(TENANT, recent)
    assert await store.insert_inbound(TENANT, old)
    await store.set_inbound_status(recent.wamid, "processing")
    async with get_async_session_maker()() as session:
        await session.execute(
            update(WhatsAppMessage)
            .where(WhatsAppMessage.wamid == old.wamid)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=2))
        )
        await session.commit()

    enqueued = []
    monkeypatch.setattr(dispatcher, "enqueue", lambda t, w: enqueued.append((t, w)))
    assert await dispatcher.resume_pending() == 1
    assert enqueued == [(TENANT, recent.wamid)]
    expired = await _row(old.wamid)
    assert (expired.status, expired.error_code) == ("failed", "expired")
    assert expired.payload_json is None


@pytest.mark.anyio
async def test_ensure_conversation(wa_db):
    from src.channels.whatsapp import dispatcher
    from src.data.engine import get_async_session_maker
    from src.data.models import Conversation

    cid = await dispatcher._ensure_conversation(
        conversation_id=None,
        user_id="mario",
        tenant_id=TENANT,
        profile_slug="aion_std",
        first_text="Quanti   ordini\nieri? " + "x" * 80,
    )
    async with get_async_session_maker()() as session:
        conv = await session.get(Conversation, cid)
        assert json.loads(conv.metadata_json) == {"source": "whatsapp"}
        assert conv.user_id == "mario" and conv.profile_slug == "aion_std"
        assert conv.title.startswith("Quanti ordini ieri?") and len(conv.title) <= 60

    same = await dispatcher._ensure_conversation(
        conversation_id=cid,
        user_id="mario",
        tenant_id=TENANT,
        profile_slug="aion_std",
        first_text="altro",
    )
    assert same == cid

    # Conversazione di un altro utente o archiviata → nuova.
    other = await dispatcher._ensure_conversation(
        conversation_id=cid,
        user_id="giulia",
        tenant_id=TENANT,
        profile_slug="aion_std",
        first_text="ciao",
    )
    assert other != cid
    async with get_async_session_maker()() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == cid)
            .values(archived_at=datetime.now(timezone.utc))
        )
        await session.commit()
    assert (
        await dispatcher._ensure_conversation(
            conversation_id=cid,
            user_id="mario",
            tenant_id=TENANT,
            profile_slug="aion_std",
            first_text="ciao",
        )
        != cid
    )


@pytest.mark.anyio
async def test_run_turn_streams_through_pipeline(wa_db, monkeypatch):
    """``run_turn`` con agente e pipeline finti: conversazione, eventi, testo finale."""
    import src.agent_pipeline as agent_pipeline
    import src.api.v1.chat as chat_mod
    import src.main as main_mod
    from src.channels.whatsapp import dispatcher, linking

    cfg = await configure_channel()
    ident = await _link()
    seen = {}

    async def fake_get_agent(profile, **kwargs):
        seen["agent"] = (profile, kwargs)
        return object(), profile

    class FakePipeline:
        def __init__(self, **kwargs):
            seen["pipeline"] = kwargs

        async def run_stream(self, text, **kwargs):
            seen["stream"] = (text, kwargs)
            # Durante il turno la run è visibile alla chat-ui.
            assert kwargs and chat_mod._background_runs
            yield {"type": "token", "content": "Ie"}
            yield {"type": "token", "content": "ri"}
            yield {"type": "final", "text": "Ieri 12 ordini"}

    async def fake_runtime(runtime, uid, profile_name):
        return {}

    async def fake_profile(user_row_id, preferred):
        return "aion_std"

    monkeypatch.setattr(main_mod, "get_agent", fake_get_agent)
    monkeypatch.setattr(main_mod, "set_event_loop", lambda loop: None)
    monkeypatch.setattr(agent_pipeline, "AgentPipeline", FakePipeline)
    monkeypatch.setattr(chat_mod, "_clamped_runtime", fake_runtime)
    monkeypatch.setattr(dispatcher, "_resolve_profile", fake_profile)

    from src.data.engine import get_async_session_maker
    from src.data.models import User

    async with get_async_session_maker()() as session:
        user = await session.get(User, "u1")

    conversation_id, profile = await dispatcher._resolve_conversation(
        tenant_id=TENANT, cfg=cfg, ident=ident, user=user, first_text="Quanti?"
    )
    result = await dispatcher.run_turn(
        tenant_id=TENANT,
        cfg=cfg,
        user=user,
        conversation_id=conversation_id,
        profile=profile,
        text="Quanti?",
        wamid="w1",
    )

    assert result.text == "Ieri 12 ordini" and not result.timed_out
    assert result.conversation_id == conversation_id and result.files == []
    profile, kwargs = seen["agent"]
    assert profile == "aion_std"
    assert kwargs["session_id"] == result.conversation_id
    assert kwargs["user_id"] == "mario"
    text, stream_kwargs = seen["stream"]
    assert text == "Quanti?"
    assert stream_kwargs["metadata"] == {"channel": "whatsapp", "wamid": "w1"}
    # No uploads: an explicit empty turn list keeps the pipeline from
    # re-persisting ``attachments`` as this turn's user attachments.
    assert stream_kwargs["attachments"] is None
    assert stream_kwargs["turn_attachments"] == []
    assert result.conversation_id not in chat_mod._background_runs
    assert (
        await linking.get_identity(TENANT, BSUID)
    ).active_conversation_id == result.conversation_id


def test_resolve_thinking(monkeypatch):
    """Channel thinking level -> turn reasoning, mirroring chat-ui's toggle+effort."""
    from src.channels.whatsapp import dispatcher

    monkeypatch.delenv("AION_DEFAULT_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("AION_THINKING_ENABLED", raising=False)

    class Cfg:  # only the field read by _resolve_thinking
        def __init__(self, level):
            self.default_thinking_level = level

    assert dispatcher._resolve_thinking(Cfg("off")) == "off"
    # An explicit "min" is low-effort thinking (toggle on), not "off".
    assert dispatcher._resolve_thinking(Cfg("min")) == "min"
    assert dispatcher._resolve_thinking(Cfg("medium")) == "medium"
    assert dispatcher._resolve_thinking(Cfg("max")) == "max"

    # Unset -> system default: medium without env, env overrides apply.
    assert dispatcher._resolve_thinking(Cfg(None)) == "medium"
    monkeypatch.setenv("AION_DEFAULT_REASONING_EFFORT", "max")
    assert dispatcher._resolve_thinking(Cfg(None)) == "max"
    # An explicit channel level wins over the env default.
    assert dispatcher._resolve_thinking(Cfg("off")) == "off"


@pytest.mark.anyio
@pytest.mark.parametrize("level,expected", [("off", "off"), ("max", "max")])
async def test_run_turn_passes_thinking_level(wa_db, monkeypatch, level, expected):
    """``run_turn`` forwards the channel thinking level as ``reasoning_effort``."""
    import src.agent_pipeline as agent_pipeline
    import src.api.v1.chat as chat_mod
    import src.main as main_mod
    from src.channels.whatsapp import dispatcher

    cfg = replace(await configure_channel(), default_thinking_level=level)
    ident = await _link()
    seen = {}

    async def fake_get_agent(profile, **kwargs):
        return object(), profile

    class FakePipeline:
        def __init__(self, **kwargs):
            pass

        async def run_stream(self, text, **kwargs):
            seen["kwargs"] = kwargs
            yield {"type": "final", "text": "ok"}

    async def fake_runtime(runtime, uid, profile_name):
        return {}

    async def fake_profile(user_row_id, preferred):
        return "aion_std"

    monkeypatch.setattr(main_mod, "get_agent", fake_get_agent)
    monkeypatch.setattr(main_mod, "set_event_loop", lambda loop: None)
    monkeypatch.setattr(agent_pipeline, "AgentPipeline", FakePipeline)
    monkeypatch.setattr(chat_mod, "_clamped_runtime", fake_runtime)
    monkeypatch.setattr(dispatcher, "_resolve_profile", fake_profile)

    from src.data.engine import get_async_session_maker
    from src.data.models import User

    async with get_async_session_maker()() as session:
        user = await session.get(User, "u1")

    conversation_id, profile = await dispatcher._resolve_conversation(
        tenant_id=TENANT, cfg=cfg, ident=ident, user=user, first_text="Ciao"
    )
    result = await dispatcher.run_turn(
        tenant_id=TENANT,
        cfg=cfg,
        user=user,
        conversation_id=conversation_id,
        profile=profile,
        text="Ciao",
        wamid="w2",
    )
    assert seen["kwargs"]["reasoning_effort"] == expected

    # chat-ui restores its Thinking toggle/effort from the conversation
    # metadata: it must mirror the level the WhatsApp turn actually used.
    async with get_async_session_maker()() as session:
        from src.data.models import Conversation

        conv = await session.get(Conversation, result.conversation_id)
    meta = json.loads(conv.metadata_json)
    assert meta["source"] == "whatsapp"
    assert meta["thinking_enabled"] is (level != "off")
    if level == "off":
        assert "reasoning_effort" not in meta
    else:
        assert meta["reasoning_effort"] == level


# ---------------------------------------------------------------------------
# Media (images/documents in, generated files out)
# ---------------------------------------------------------------------------


@pytest.fixture
def media_store(monkeypatch):
    """No object-storage copy / PDF auto-ingest during dispatcher media tests.

    Session files go to ``AION_DATA_DIR`` (a ``tmp_path``, see ``setup_db``).
    """
    from src.channels.whatsapp import media

    class _Backend:
        def put_bytes(self, key, data, mime):
            pass

    monkeypatch.setattr(media, "get_storage_backend", lambda: _Backend())
    monkeypatch.setattr(media, "schedule_auto_ingest", lambda cid, meta: None)


async def _identity():
    from src.channels.whatsapp import linking

    return await linking.get_identity(TENANT, BSUID)


@pytest.mark.anyio
async def test_captioned_image_runs_turn_with_attachment(
    wa_db, graph, turns, media_store
):
    """A photo with a caption is stored in uploads/ and sent with the turn."""
    from src.session_workspace import session_root

    await configure_channel()
    await _link()
    row = await _deliver(_msg(fixture="image"))

    assert row.status == "done"
    (call,) = turns.calls
    assert call["text"] == "scontrino"
    (att,) = call["turn_attachments"]
    assert att["relative_path"].startswith("uploads/")
    assert att["original_name"].startswith("whatsapp_")
    assert att["mime"] == "image/jpeg"
    assert "added_at" not in att and "conversation_id" not in att
    path = session_root(call["conversation_id"]) / att["relative_path"]
    assert path.read_bytes() == graph.media_bytes
    # The media id from the webhook (no url) is resolved via GET /{media-id}.
    assert "mid=MEDIA1" in graph.downloaded[0]
    assert graph.bodies[0].startswith("*Ieri 12 ordini*")


@pytest.mark.anyio
async def test_album_without_caption_waits_for_text(wa_db, graph, turns, media_store):
    """Caption-less burst: one ack, then read receipts; the next text gets all files."""
    from src.channels.whatsapp.dispatcher import MESSAGES

    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="image_no_caption"))
    # A document without caption (``text`` is a positional arg of ``_msg``).
    second = replace(_msg(fixture="document_pdf"), text=None)
    await _deliver(second)

    assert turns.calls == []
    assert graph.bodies == [MESSAGES["media_received"]]
    assert graph.read == [second.wamid]
    pending = json.loads((await _identity()).pending_attachments_json)
    assert [p["original_name"] for p in pending][1] == "Fattura marzo.pdf"

    await _deliver(_msg("Riassumi tutto"))
    (call,) = turns.calls
    assert call["text"] == "Riassumi tutto"
    assert len(call["turn_attachments"]) == 2
    assert (await _identity()).pending_attachments_json is None


@pytest.mark.anyio
async def test_new_conversation_clears_pending(wa_db, graph, turns, media_store):
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="image_no_caption"))
    assert (await _identity()).pending_attachments_json

    await _deliver(_msg("/nuova"))
    ident = await _identity()
    assert ident.pending_attachments_json is None
    assert ident.active_conversation_id is None

    await _deliver(_msg("Ciao"))
    assert turns.calls[0]["turn_attachments"] == []


@pytest.mark.anyio
async def test_expired_pending_is_dropped(wa_db, graph, turns, media_store):
    """Pending files older than 24h are not attached to the next message."""
    await configure_channel()
    ident = await _link()
    await _deliver(_msg(fixture="image_no_caption"))
    from src.channels.whatsapp import linking

    stale = json.loads((await _identity()).pending_attachments_json)
    stale[0]["added_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=25)
    ).isoformat()
    await linking.update_identity(ident.id, pending_attachments_json=json.dumps(stale))

    await _deliver(_msg("E quindi?"))
    assert turns.calls[0]["turn_attachments"] == []
    assert (await _identity()).pending_attachments_json is None


@pytest.mark.anyio
async def test_media_too_large(wa_db, graph, turns, media_store):
    from src.channels.whatsapp.graph_client import MediaTooLarge

    await configure_channel()
    await _link()
    graph.download_error = MediaTooLarge("big")
    await _deliver(_msg(fixture="image"))
    assert turns.calls == []
    (body,) = graph.bodies
    assert "MB" in body and "https://aion.example.com/c/" in body


@pytest.mark.anyio
async def test_media_download_failure(wa_db, graph, turns, media_store):
    from src.channels.whatsapp.dispatcher import MESSAGES
    from src.channels.whatsapp.graph_client import GraphError

    await configure_channel()
    await _link()
    graph.download_error = GraphError("boom", status=500)
    row = await _deliver(_msg(fixture="document_pdf"))
    assert row.status == "done"
    assert graph.bodies == [MESSAGES["media_failed"]]
    assert turns.calls == []


def _write_outputs(conversation_id, *rels):
    from src.session_workspace import session_root

    root = session_root(conversation_id)
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"content")
    return list(rels)


@pytest.mark.anyio
async def test_generated_files_sent_after_text(wa_db, graph, turns, media_store):
    """Agent outputs are uploaded and sent as image/document after the answer."""
    from src.channels.whatsapp import dispatcher

    await configure_channel()
    await _link()
    files = _write_outputs("conv-1", "workspace/report.xlsx", "derived/grafico.png")
    turns.reply = dispatcher.TurnResult(
        conversation_id="conv-1", text="Ecco il report", files=files
    )
    await _deliver(_msg("Creami un excel"))

    assert graph.sent[0]["body"].startswith("Ecco il report")
    kinds = [(m["kind"], m.get("filename")) for m in graph.media_sent]
    assert kinds == [("document", "report.xlsx"), ("image", "grafico.png")]
    assert [u["filename"] for u in graph.uploads] == ["report.xlsx", "grafico.png"]
    assert all(s["to"] == "393331112233" for s in graph.sent)


@pytest.mark.anyio
async def test_files_only_reply_skips_empty_message(wa_db, graph, turns, media_store):
    """No text but a file: the file is the answer, no "empty reply" message."""
    from src.channels.whatsapp import dispatcher

    await configure_channel()
    await _link()
    files = _write_outputs("conv-1", "workspace/out.pdf")
    turns.reply = dispatcher.TurnResult(conversation_id="conv-1", text="", files=files)
    await _deliver(_msg("Fammi il pdf"))
    assert graph.bodies == []
    assert [m["kind"] for m in graph.media_sent] == ["document"]


@pytest.mark.anyio
async def test_extra_files_are_linked(wa_db, graph, turns, media_store, monkeypatch):
    """Past ``AION_WHATSAPP_MAX_OUTBOUND_FILES`` the rest is linked to chat-ui."""
    from src.channels.whatsapp import dispatcher

    monkeypatch.setenv("AION_WHATSAPP_MAX_OUTBOUND_FILES", "1")
    await configure_channel()
    await _link()
    files = _write_outputs("conv-1", "workspace/a.pdf", "workspace/b.pdf")
    turns.reply = dispatcher.TurnResult(
        conversation_id="conv-1", text="Ok", files=files
    )
    await _deliver(_msg("Due pdf"))
    assert len(graph.media_sent) == 1
    assert graph.bodies[-1] == dispatcher.MESSAGES["more_files"].format(
        count=1, conversation_url="https://aion.example.com/c/conv-1"
    )


# ---------------------------------------------------------------------------
# Voice notes (audio in, transcript as the user's text)
# ---------------------------------------------------------------------------


@pytest.fixture
def stt(monkeypatch):
    """Replaces ``voice.transcribe_voice_note``: returns ``stt.result``, records calls."""
    from src.channels.whatsapp import voice

    class _Stt:
        calls: list = []
        result = voice.VoiceTranscript(text="Quanti ordini ieri?", duration_sec=3.0)

    state = _Stt()
    state.calls = []

    async def fake_transcribe(conversation_id, attachment):
        state.calls.append((conversation_id, attachment))
        return state.result

    monkeypatch.setattr(voice, "transcribe_voice_note", fake_transcribe)
    return state


async def _conversation(conversation_id):
    from src.data.engine import get_async_session_maker
    from src.data.models import Conversation

    async with get_async_session_maker()() as session:
        return await session.get(Conversation, conversation_id)


@pytest.mark.anyio
async def test_voice_note_runs_turn_with_transcript_and_audio(
    wa_db, graph, turns, media_store, stt
):
    """The transcript (🎤-prefixed) is the turn text, the .ogg is attached, no echo."""
    from src.channels.whatsapp.dispatcher import MESSAGES, VOICE_TITLE_PLACEHOLDER

    await configure_channel()
    await _link()
    row = await _deliver(_msg(fixture="audio_voice"))

    assert row.status == "done"
    (call,) = turns.calls
    assert call["text"] == "🎤 Quanti ordini ieri?"
    (att,) = call["turn_attachments"]
    assert att["original_name"].startswith("vocale_")
    assert att["original_name"].endswith(".ogg")
    assert stt.calls == [(call["conversation_id"], att)]
    # Only the agent's answer is sent: no transcript echo, no "received" ack.
    assert graph.bodies[0].startswith("*Ieri 12 ordini*")
    assert MESSAGES["media_received"] not in graph.bodies
    # The placeholder title of the new conversation is replaced by the transcript.
    conv = await _conversation(call["conversation_id"])
    assert conv.title == "🎤 Quanti ordini ieri?" != VOICE_TITLE_PLACEHOLDER


@pytest.mark.anyio
async def test_voice_note_consumes_pending_files(wa_db, graph, turns, media_store, stt):
    """Photo without caption + voice note "cos'è?" = one turn with both files."""
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="image_no_caption"))
    await _deliver(_msg(fixture="audio_voice"))

    (call,) = turns.calls
    assert [a["original_name"][:7] for a in call["turn_attachments"]] == [
        "whatsap",
        "vocale_",
    ]
    assert (await _identity()).pending_attachments_json is None


@pytest.mark.anyio
async def test_partial_transcript_is_flagged(wa_db, graph, turns, media_store, stt):
    from src.channels.whatsapp import voice
    from src.channels.whatsapp.dispatcher import MESSAGES

    stt.result = voice.VoiceTranscript(text="Prima parte", partial=True)
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="audio_voice"))

    assert turns.calls[0]["text"] == f"🎤 Prima parte\n{MESSAGES['voice_partial']}"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error, key",
    [
        ("too_long", "voice_too_long"),
        ("no_speech", "voice_empty"),
        ("engine_failed", "voice_failed"),
    ],
)
async def test_voice_note_failures_reply_without_turn(
    wa_db, graph, turns, media_store, stt, monkeypatch, error, key
):
    """A failed transcription is explained to the user; pending files keep waiting."""
    from src.channels.whatsapp import voice
    from src.channels.whatsapp.dispatcher import MESSAGES

    monkeypatch.setenv("AION_WHATSAPP_VOICE_MAX_SEC", "300")
    stt.result = voice.VoiceTranscript(error=error)
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="image_no_caption"))
    row = await _deliver(_msg(fixture="audio_voice"))

    assert row.status == "done"
    assert turns.calls == []
    assert graph.bodies[-1] == MESSAGES[key].format(max_min=5)
    assert len(json.loads((await _identity()).pending_attachments_json)) == 1


@pytest.mark.anyio
async def test_voice_disabled(wa_db, graph, turns, media_store, stt, monkeypatch):
    """``AION_WHATSAPP_VOICE=0``: voice notes are declined without downloading them."""
    from src.channels.whatsapp.dispatcher import MESSAGES

    monkeypatch.setenv("AION_WHATSAPP_VOICE", "0")
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="audio_voice"))

    assert graph.bodies == [MESSAGES["voice_disabled"]]
    assert graph.downloaded == [] and turns.calls == [] and stt.calls == []
