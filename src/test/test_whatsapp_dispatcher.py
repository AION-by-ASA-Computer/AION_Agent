"""Dispatcher: collegamento, comandi, turno dell'agente, risposte, ripresa."""

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

    state = _Turns()
    state.calls = []

    async def fake_run_turn(**kwargs):
        state.calls.append(kwargs)
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
    await configure_channel()
    await _link()
    await _deliver(_msg(fixture="image"))
    assert graph.bodies == [
        "Per ora posso leggere solo messaggi di testo. Scrivimi la domanda 🙂"
    ]
    assert turns.calls == []


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

    result = await dispatcher.run_turn(
        tenant_id=TENANT, cfg=cfg, ident=ident, user=user, text="Quanti?", wamid="w1"
    )

    assert result.text == "Ieri 12 ordini" and not result.timed_out
    profile, kwargs = seen["agent"]
    assert profile == "aion_std"
    assert kwargs["session_id"] == result.conversation_id
    assert kwargs["user_id"] == "mario"
    text, stream_kwargs = seen["stream"]
    assert text == "Quanti?"
    assert stream_kwargs["metadata"] == {"channel": "whatsapp", "wamid": "w1"}
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

    result = await dispatcher.run_turn(
        tenant_id=TENANT, cfg=cfg, ident=ident, user=user, text="Ciao", wamid="w2"
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
