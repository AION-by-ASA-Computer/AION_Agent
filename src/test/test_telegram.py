"""Canale Telegram: test delle funzioni principali.

Bot API, account, adapter e sessioni sono finti; DB SQLite temporaneo dove serve.
Sezioni: infrastruttura · collegamento · chat · rich e allegati · assistenti ·
bot figli e supervisor · condivisi e gruppi · amministrazione.
"""

import asyncio
import io
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramUnauthorizedError
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteWebhook,
    EditMessageText,
    GetManagedBotToken,
    GetMe,
    GetUpdates,
    LeaveChat,
    ReplaceManagedBotToken,
    SendMessage,
    SendMessageDraft,
    SendRichMessage,
    SendRichMessageDraft,
    SetManagedBotAccessSettings,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    Document,
    ManagedBotCreated,
    ManagedBotUpdated,
    Message,
    MessageEntity,
    MessageGenerationStopped,
    ReplyKeyboardMarkup,
    Update,
    User,
    Voice,
)
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.channels.telegram import config as tg_config, runtime
from src.channels.telegram.accounts import (
    PAIR_PREFIX,
    LinkInfo,
    RedeemStatus,
    TelegramAccounts,
)
from src.channels.telegram.adapter import (
    AionUserRef,
    ChatAccessError,
    Final,
    ProfileInfo,
    ProjectInfo,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolResult,
)
from src.channels.telegram.bots import (
    OWNER_CHANGED_REASON,
    UNLINKED_REASON,
    BotFactory,
    BotStatus,
    QuotaExceeded,
    TelegramBots,
)
from src.channels.telegram.chat import ChatService, ChatSession
from src.channels.telegram.config import TelegramSettings
from src.channels.telegram.formatting import markdown_to_html, split_markdown
from src.channels.telegram.gateway import build_child_dispatcher, build_dispatcher
from src.channels.telegram.handlers import bots as hb, child as hc
from src.channels.telegram.models import TgBot, TgLink, ensure_schema
from src.channels.telegram.poller import UpdatePoller
from src.channels.telegram.redact import install_log_redaction, redact
from src.channels.telegram.supervisor import BotSupervisor
from src.data.bootstrap import ensure_bootstrap_schema
from src.data.engine import get_async_session_maker, init_engine
from src.data.models import Conversation
from src.data.models import User as AionUser

U1_TG, U2_TG, STRANGER_TG = 777, 888, 4242
GROUP_ID = -500
MANAGER = User(id=4242000, is_bot=True, first_name="AION", username="aion_test_bot")
CHILD = User(id=9001, is_bot=True, first_name="Assistente RAG", username="rag_bot")
CHILD_TOKEN = "9001:" + "C" * 35
OWNER = User(id=U1_TG, is_bot=False, first_name="Ann")
COLLEAGUE = User(id=U2_TG, is_bot=False, first_name="Marco")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", "11" * 32)


@pytest.fixture()
def tg_db(monkeypatch, tmp_path):
    """DB SQLite temporaneo con le tabelle di AION e del canale, utenti u1 e u2."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'tg.db'}"
    monkeypatch.setenv("AION_DB_URL", url)
    import src.data.engine as eng_mod

    eng_mod._engine = None
    eng_mod._session_factory = None
    eng = init_engine(url)

    async def setup():
        await ensure_bootstrap_schema(eng)
        await ensure_schema()
        await ensure_schema()  # idempotente
        async with get_async_session_maker()() as s:
            for uid in ("u1", "u2"):
                s.add(AionUser(id=uid, tenant_id="default", identifier=f"user-{uid}"))
            await s.commit()

    _run(setup())
    yield url
    _run(eng.dispose())
    eng_mod._engine = None
    eng_mod._session_factory = None


# ======================================================================
# Finti condivisi
# ======================================================================
class FakeApi(BaseSession):
    """Bot API finta: registra le chiamate e risponde il minimo indispensabile."""

    def __init__(self, *, me=MANAGER, rich=True, fail=(), unauthorized=False):
        super().__init__()
        self.requests = []
        self.me, self.rich, self.fail = me, rich, tuple(fail)
        self.unauthorized = unauthorized
        self.token = CHILD_TOKEN
        self.closed = False

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if self.unauthorized:
            raise TelegramUnauthorizedError(method=method, message="Unauthorized")
        if isinstance(method, self.fail):
            raise RuntimeError("api down")
        if isinstance(method, GetMe):
            return self.me
        if (
            isinstance(method, (SendRichMessage, SendRichMessageDraft))
            and not self.rich
        ):
            raise TelegramBadRequest(
                method=method, message="Bad Request: method not found"
            )
        if isinstance(method, (GetManagedBotToken, ReplaceManagedBotToken)):
            return self.token
        if isinstance(method, GetUpdates):
            await asyncio.sleep(0.02)
            return []
        if isinstance(method, (SendMessage, EditMessageText, SendRichMessage)):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=getattr(method, "text", None),
            )
        return True

    def of(self, kind):
        return [r for r in self.requests if isinstance(r, kind)]

    def texts(self):
        return [m.text for m in self.of(SendMessage)]

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    async def close(self):
        self.closed = True


def _bot(api, token="4242000:" + "M" * 35):
    return Bot(token=token, session=api)


class FakeAccounts:
    """Account Telegram collegati: 777 → u1, 888 → u2."""

    def __init__(self, links=None):
        self.links = {U1_TG: "u1", U2_TG: "u2"} if links is None else links

    async def get_link_for_tg(self, tg_user_id):
        aion = self.links.get(tg_user_id)
        return LinkInfo(aion, tg_user_id, "ann", "Ann", None, None) if aion else None

    async def touch(self, *a, **k):
        pass


class FakeAdapter:
    """AION finto. Il progetto «vendite» è solo di u1; «segreto» di nessuno."""

    def __init__(self, events=None, delay=0.0):
        self.events = events or [
            TextDelta("Ciao "),
            TextDelta("**mondo**"),
            Final("Ciao **mondo**"),
        ]
        self.delay = delay
        self.turns = []  # (utente, testo, profilo, progetto, allegati, utente progetto)
        self.created = []
        self.cancelled = []
        self.saved = []

    async def resolve_user(self, row_id):
        return AionUserRef(
            row_id=row_id, identifier=f"user-{row_id}", display_name=row_id
        )

    async def resolve_profile(self, user, requested):
        if requested == "vietato":
            raise ChatAccessError("Il profilo «vietato» non è consentito")
        return requested or "generic_assistant"

    def profile_name(self, slug):
        return {"generic_assistant": "Generic Assistant", "rag": "RAG"}.get(slug, slug)

    async def list_profiles(self, user):
        return [
            ProfileInfo("generic_assistant", "Generic Assistant", ""),
            ProfileInfo("rag", "RAG", ""),
        ]

    async def list_projects(self, user, profile):
        return [ProjectInfo("vendite", "Vendite")]

    async def check_project(self, user, project, profile):
        if project == "segreto" or (
            project == "vendite" and user.identifier != "user-u1"
        ):
            raise ChatAccessError(f"Progetto «{project}» non accessibile")

    async def create_conversation(
        self, user, *, profile_slug, project_slug, extra_metadata=None
    ):
        cid = f"conv-{len(self.created) + 1}"
        self.created.append((cid, profile_slug, project_slug, extra_metadata))
        return cid

    async def sync_conversation(self, user, cid, *, profile_slug, project_slug):
        return True

    async def save_attachment(self, cid, name, data):
        self.saved.append((name, data))
        return {"relative_path": f"uploads/{name}"}

    async def chat_stream(
        self,
        user,
        cid,
        text,
        *,
        profile_slug,
        project_slug,
        attachments=None,
        project_user=None,
    ):
        self.turns.append(
            (user.row_id, text, profile_slug, project_slug, attachments, project_user)
        )
        for ev in self.events:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield ev

    async def cancel(self, cid):
        self.cancelled.append(cid)


class FakeSessions:
    def __init__(self):
        self.rows = {}

    async def get_or_create(
        self, *, bot_id, chat_id, tg_user_id, aion_user_id, thread_id=None
    ):
        key = (bot_id, chat_id, thread_id or 0, tg_user_id)
        if key not in self.rows:
            self.rows[key] = ChatSession(
                len(self.rows) + 1, aion_user_id, None, None, None
            )
        return self.rows[key]

    async def update(self, session_id, **fields):
        for key, row in self.rows.items():
            if row.id == session_id:
                self.rows[key] = ChatSession(**(row.__dict__ | fields))
                return self.rows[key]
        raise LookupError(session_id)


class FakeSupervisor:
    def __init__(self):
        self.calls = []

    async def ensure(self, info):
        self.calls.append(("ensure", info.status))

    async def restart(self, info):
        self.calls.append(("restart", info.status))

    async def stop(self, bot_tg_id):
        self.calls.append(("stop", bot_tg_id))


def _settings(**kw):
    base = dict(
        _env_file=None, enabled=True, stream_edit_interval_ms=300, max_concurrent_jobs=1
    )
    return TelegramSettings(**(base | kw))


def _msg(uid, *, chat_id=U1_TG, chat_type="private", user=OWNER, title=None, **fields):
    return Message(
        message_id=uid,
        date=datetime.now(timezone.utc),
        chat=Chat(id=chat_id, type=chat_type, title=title),
        from_user=user,
        **fields,
    )


def _callback(uid, data, user=OWNER):
    return CallbackQuery(
        id=str(uid),
        from_user=user,
        chat_instance="ci",
        data=data,
        message=_msg(1, chat_id=user.id, text="menu"),
    )


async def _drain(chat):
    while chat._tasks:
        await asyncio.gather(*list(chat._tasks), return_exceptions=True)


def _factory(*, accounts=None, child_api=None, **settings):
    """BotFactory su DB reale e Bot API finta (anche per i bot figli)."""
    apis = []

    def child_bot(token, s):
        api = child_api() if child_api else FakeApi(me=CHILD)
        apis.append(api)
        return _bot(api, token)

    factory = BotFactory(
        bots=TelegramBots(),
        accounts=accounts or FakeAccounts(),
        adapter=FakeAdapter(),
        settings=TelegramSettings(_env_file=None, **settings),
        child_bot=child_bot,
    )
    factory.can_manage_bots = True
    factory.manager_username = "aion_test_bot"
    factory.child_apis = apis
    return factory


async def _seed_bot(
    bots, *, tg_id=CHILD.id, owner="u1", owner_tg=U1_TG, status=BotStatus.ACTIVE, **kw
):
    return await bots.create(
        owner_aion_user_id=owner,
        owner_tg_user_id=owner_tg,
        bot_tg_id=tg_id,
        username=kw.get("username", "rag_bot"),
        name=kw.get("name", "Assistente RAG"),
        profile_slug=kw.get("profile", "rag"),
        project_slug=kw.get("project"),
        token=kw.get("token", CHILD_TOKEN),
        status=status,
        last_error=kw.get("last_error"),
        mode=kw.get("mode", "personal"),
    )


# ======================================================================
# Infrastruttura: token nei log, formattazione, polling
# ======================================================================
def test_tokens_never_reach_logs(caplog):
    token = "1234567890:AAH9xk-Qe_7sdfLKJ23lkjSDF98sdflkjSDf"
    assert token not in redact(f"https://api.telegram.org/bot{token}/getMe")
    assert redact("chat 12345 id 678:short") == "chat 12345 id 678:short"
    install_log_redaction()
    with caplog.at_level(logging.INFO, logger="aion.telegram"):
        logging.getLogger("aion.telegram").info("calling bot%s", token)
    assert token not in caplog.text


def test_markdown_to_telegram_html_and_split():
    html = markdown_to_html("**B** *i* `x<y>` & <script>\n```python\na**2\n```")
    assert "<b>B</b>" in html and "<i>i</i>" in html and "&lt;script&gt;" in html
    assert '<pre><code class="language-python">a**2</code></pre>' in html
    md = "Intro\n```python\n" + "\n".join("x" * 60 for _ in range(200)) + "\n```\nFine"
    chunks = split_markdown(md, limit=1000)
    assert len(chunks) > 3 and all(c.count("```") % 2 == 0 for c in chunks)


class _PollBot:
    def __init__(self, batches):
        self.batches, self.calls = list(batches), []

    async def get_updates(self, offset=None, limit=None, timeout=None, **kw):
        self.calls.append(offset)
        if timeout == 0 and limit == 1:
            return []
        if self.batches:
            return [Update(update_id=i) for i in self.batches.pop(0)]
        await asyncio.sleep(3600 if timeout else 0)
        return []


class _PollDispatcher:
    def __init__(self, blocking=()):
        self.blocking, self.handled = set(blocking), []

    async def feed_update(self, bot, update):
        if update.update_id in self.blocking:
            await asyncio.sleep(3600)
        self.handled.append(update.update_id)


def test_poller_never_confirms_update_in_progress():
    async def scenario():
        bot, dp = _PollBot([[5, 6], [5, 6]]), _PollDispatcher(blocking={5})
        poller = UpdatePoller(
            bot, dp, name="t", polling_timeout=50, shutdown_grace_sec=0.05
        )
        task = asyncio.create_task(poller.run())
        for _ in range(200):
            if len(bot.calls) >= 3:
                break
            await asyncio.sleep(0.01)
        await poller.stop()
        await asyncio.wait_for(task, 1)
        return bot, dp

    bot, dp = _run(scenario())
    assert dp.handled == [6]  # niente doppio dispatch
    assert max(c or 0 for c in bot.calls) == 5  # l'offset non supera l'update in corso


# ======================================================================
# Collegamento account
# ======================================================================
def test_pairing_code_single_use_and_hashed(tg_db):
    from src.channels.telegram.models import TgPairingCode

    acc = TelegramAccounts()
    code = _run(acc.create_pairing_code("u1", ttl_min=15))
    assert code.start_param.startswith(PAIR_PREFIX) and len(code.start_param) <= 64
    status, link = _run(acc.redeem_pairing_code(code.code, tg_user_id=U1_TG))
    assert status is RedeemStatus.LINKED and link.aion_user_id == "u1"
    assert (
        _run(acc.redeem_pairing_code(code.code, tg_user_id=U1_TG))[0]
        is RedeemStatus.USED
    )

    async def stored():
        async with get_async_session_maker()() as s:
            return (await s.execute(select(TgPairingCode))).scalars().all()

    assert all(code.code not in r.code_hash for r in _run(stored()))


def test_unlinked_users_can_only_use_public_commands():
    async def scenario():
        api = FakeApi()
        dp = build_dispatcher(
            accounts=FakeAccounts(links={}),
            adapter=FakeAdapter(),
            chat=None,
            settings=_settings(),
        )
        bot = _bot(api)
        await dp.feed_update(bot, Update(update_id=1, message=_msg(1, text="/whoami")))
        await dp.feed_update(bot, Update(update_id=2, message=_msg(2, text="/newbot")))
        await dp.feed_update(bot, Update(update_id=3, message=_msg(3, text="ciao")))
        return api

    texts = _run(scenario()).texts()
    assert f"<code>{U1_TG}</code>" in texts[0]
    assert all("non è collegato ad AION" in t for t in texts[1:])


@pytest.fixture()
def me_client(tg_db, monkeypatch):  # noqa: F811
    from src.api.auth_login import ChatAuthIdentity
    from src.api.v1 import me_telegram

    monkeypatch.setattr(
        me_telegram, "get_telegram_settings", lambda: _settings(pairing_code_ttl_min=15)
    )

    class Gateway:
        bot_username = "aion_test_bot"
        bot = None

        def __init__(self):
            self.texts = []
            self.dispatcher = {"bot_factory": _factory()}

        async def notify(self, tg_user_id, text):
            self.texts.append(text)

    gw = Gateway()
    runtime.set_gateway(gw)
    app = FastAPI()
    app.include_router(me_telegram.router, prefix="/v1")
    app.dependency_overrides[me_telegram._me] = lambda: ChatAuthIdentity(
        via="chat_token", user_row_id="u1", identifier="user-u1"
    )
    with TestClient(app) as c:
        c.gateway = gw
        yield c
    runtime.set_gateway(None)


def test_chat_ui_link_then_unlink_suspends_assistants(me_client):
    url = me_client.post("/v1/me/telegram/link").json()["url"]
    assert url.startswith("https://t.me/aion_test_bot?start=pair_")
    _run(
        TelegramAccounts().redeem_pairing_code(url.split("pair_")[1], tg_user_id=U1_TG)
    )
    assert me_client.get("/v1/me/telegram").json()["link"]["tg_user_id"] == U1_TG
    bots = TelegramBots()
    _run(_seed_bot(bots))
    assert (
        me_client.get("/v1/me/telegram/bots").json()["data"][0]["url"]
        == "https://t.me/rag_bot"
    )
    assert me_client.delete("/v1/me/telegram/link").json() == {
        "ok": True,
        "suspended_bots": 1,
    }
    [bot] = _run(bots.list_for_owner("u1"))
    assert bot.status == "suspended" and bot.last_error == UNLINKED_REASON


# ======================================================================
# Chat con l'agente (logica comune; qui sul manager in modalità emergenza)
# ======================================================================
class ChatHarness:
    def __init__(self, adapter=None, *, rich=False, api=None, **settings):
        self.api = api or FakeApi(rich=rich)
        self.bot = _bot(self.api, "123456:TESTTOKENTESTTOKEN")
        self.adapter = adapter or FakeAdapter()
        self.chat = ChatService(
            settings=_settings(manager_chat=True, rich_messages=rich, **settings),
            adapter=self.adapter,
            sessions=FakeSessions(),
        )
        self.dp = build_dispatcher(
            accounts=FakeAccounts(),
            adapter=self.adapter,
            chat=self.chat,
            settings=self.chat.settings,
        )
        self.n = 0

    async def send(self, text=None, *, drain=True, **fields):
        self.n += 1
        await self.dp.feed_update(
            self.bot,
            Update(update_id=self.n, message=_msg(self.n, text=text, **fields)),
        )
        if drain:
            await _drain(self.chat)


def test_turn_streams_formatted_answer_with_tools():
    adapter = FakeAdapter(
        events=[
            ToolCall("srv__web_search", call_id="1"),
            ToolResult("srv__web_search", ok=True, call_id="1"),
            TextDelta("**ok**"),
            Final("**ok**"),
        ],
        delay=0.35,
    )
    h = ChatHarness(adapter)
    _run(h.send("cerca"))
    [(user, text, profile, *_)] = adapter.turns
    assert (user, text, profile) == ("u1", "cerca", "generic_assistant")
    final = h.api.of(SendMessage)[-1].text
    assert (
        final.startswith("<b>ok</b>")
        and "Strumenti usati (1)" in final
        and "web_search" in final
    )


def test_stop_command_cancels_running_turn():
    adapter = FakeAdapter(
        events=[TextDelta("a"), TextDelta("b"), Final("ab")], delay=0.3
    )
    h = ChatHarness(adapter)

    async def scenario():
        await h.send("lungo", drain=False)
        await asyncio.sleep(0.1)
        await h.send("/stop", drain=False)
        await _drain(h.chat)

    _run(scenario())
    assert adapter.cancelled == ["conv-1"]


# ======================================================================
# Formato rich, pulsante di stop, allegati, vocali
# ======================================================================
def test_rich_answer_has_reasoning_first_and_stop_button():
    adapter = FakeAdapter(
        events=[
            ReasoningDelta("Penso."),
            TextDelta("| a | b |\n|---|---|\n| 1 | 2 |"),
            Final("| a | b |\n|---|---|\n| 1 | 2 |"),
        ],
        delay=0.35,
    )
    h = ChatHarness(adapter, rich=True)
    _run(h.send("tabella?"))
    drafts = h.api.of(SendRichMessageDraft)
    assert drafts and all(d.can_stop for d in drafts)
    md = h.api.of(SendRichMessage)[-1].rich_message.markdown
    assert md.startswith("<details><summary>💭 Ragionamento</summary>")
    assert md.index("Ragionamento") < md.index(
        "| a | b |"
    )  # Markdown così com'è: tabella vera


def test_rich_rejected_falls_back_to_html_once():
    h = ChatHarness(rich=True, api=FakeApi(rich=False))
    _run(h.send("ciao"))
    _run(h.send("di nuovo"))
    assert len(h.api.of(SendMessage)) == 2
    assert len(h.api.of(SendRichMessage) + h.api.of(SendRichMessageDraft)) == 1


def test_stop_button_on_preview_cancels_turn():
    adapter = FakeAdapter(
        events=[TextDelta("a"), TextDelta("b"), Final("ab")], delay=0.4
    )
    h = ChatHarness(adapter, rich=True)

    async def scenario():
        await h.send("lungo", drain=False)
        for _ in range(40):
            if h.api.of(SendRichMessageDraft):
                break
            await asyncio.sleep(0.05)
        stop = MessageGenerationStopped(
            chat=Chat(id=U1_TG, type="private"),
            draft_id=h.api.of(SendRichMessageDraft)[0].draft_id,
        )
        await h.dp.feed_update(
            h.bot, Update(update_id=99, stopped_message_generation=stop)
        )
        await _drain(h.chat)

    _run(scenario())
    assert adapter.cancelled == ["conv-1"]


def test_file_without_caption_waits_for_question(monkeypatch):
    async def download(self, file, *a, **k):
        return io.BytesIO(b"dati")

    monkeypatch.setattr(Bot, "download", download)
    adapter = FakeAdapter()
    h = ChatHarness(adapter)
    doc = Document(
        file_id="f1", file_unique_id="f1", file_name="report.pdf", file_size=4
    )
    _run(h.send(document=doc))
    assert adapter.turns == [] and "Ricevuto «report.pdf»" in h.api.texts()[0]
    _run(h.send("riassumilo"))
    [turn] = adapter.turns
    assert turn[1] == "riassumilo" and turn[4] == [
        {"relative_path": "uploads/report.pdf"}
    ]
    # Con didascalia si parte subito; oltre 20 MB si rifiuta; i vocali hanno una risposta di cortesia.
    _run(h.send(document=doc, caption="ancora"))
    big = Document(
        file_id="f2",
        file_unique_id="f2",
        file_name="big.zip",
        file_size=25 * 1024 * 1024,
    )
    _run(h.send(document=big))
    _run(h.send(voice=Voice(file_id="v", file_unique_id="v", duration=2)))
    assert len(adapter.turns) == 2
    assert "20 MB" in h.api.texts()[-2] and "vocali" in h.api.texts()[-1]


# ======================================================================
# Assistenti: creazione, cifratura, ciclo di vita
# ======================================================================
def test_bot_token_is_stored_encrypted(tg_db):
    bots = TelegramBots()
    info = _run(_seed_bot(bots))

    async def raw():
        async with get_async_session_maker()() as s:
            return (await s.execute(select(TgBot))).scalar_one().token_enc

    assert CHILD_TOKEN not in _run(raw())
    assert _run(bots.token_for(info.id)) == CHILD_TOKEN


def test_newbot_wizard_creates_shared_assistant(tg_db):
    factory = _factory()
    api = FakeApi()
    dp = build_dispatcher(
        accounts=factory.accounts,
        adapter=factory.adapter,
        chat=None,
        bot_factory=factory,
        settings=_settings(),
    )

    async def scenario():
        bot = _bot(api)
        for n, upd in enumerate(
            [
                _msg(1, text="/newbot"),
                _msg(2, text="Assistente RAG"),
                _callback(3, hb.NEW_MODE + "shared"),
                _callback(4, hb.NEW_PROFILE + "rag"),
                _callback(5, hb.NEW_PROJECT + "vendite"),
                _callback(6, hb.NEW_OK),
                _msg(7, managed_bot_created=ManagedBotCreated(bot=CHILD)),
            ],
            start=1,
        ):
            key = "callback_query" if isinstance(upd, CallbackQuery) else "message"
            await dp.feed_update(bot, Update(update_id=n, **{key: upd}))
        # Telegram notifica anche con l'update managed_bot: nessun doppione.
        await dp.feed_update(
            bot,
            Update(update_id=8, managed_bot=ManagedBotUpdated(user=OWNER, bot=CHILD)),
        )
        return await factory.bots.get_by_tg_id(CHILD.id)

    info = _run(scenario())
    assert info.status == "active" and info.shared
    assert (info.profile_slug, info.project_slug) == ("rag", "vendite")
    keyboard = next(
        m.reply_markup
        for m in api.of(SendMessage)
        if isinstance(m.reply_markup, ReplyKeyboardMarkup)
    )
    assert (
        keyboard.keyboard[0][0].request_managed_bot.suggested_username
        == "assistente_rag_bot"
    )
    [access] = api.of(SetManagedBotAccessSettings)
    assert access.is_access_restricted is False  # condiviso: il controllo lo fa AION
    assert sum("pronto" in t for t in api.texts()) == 1


def test_delete_revokes_token_and_is_not_undone(tg_db):
    factory = _factory()
    factory.supervisor = FakeSupervisor()
    api = FakeApi()

    async def scenario():
        bot = _bot(api)
        info, _ = await factory.register(
            bot, owner=OWNER, bot_user=CHILD, refresh_token=False
        )
        await factory.delete(bot, info, actor_tg_user_id=U1_TG)
        # La revoca genera un update "token cambiato": non deve riattivarlo.
        api.token = "9001:" + "N" * 35
        await factory.register(bot, owner=OWNER, bot_user=CHILD, refresh_token=True)
        return await factory.bots.get(info.id)

    info = _run(scenario())
    assert info.status == "deleted" and not info.has_token
    assert api.of(ReplaceManagedBotToken)[0].user_id == CHILD.id
    assert factory.supervisor.calls == [("ensure", "active"), ("stop", CHILD.id)]


def test_token_rotation_restarts_listening_once(tg_db):
    factory = _factory()
    factory.supervisor = FakeSupervisor()
    api = FakeApi()

    async def scenario():
        bot = _bot(api)
        info = await _seed_bot(factory.bots)
        api.token = "9001:" + "Q" * 35
        await factory.rotate_token(bot, info, actor_tg_user_id=U1_TG)
        await factory.register(bot, owner=OWNER, bot_user=CHILD, refresh_token=True)
        return await factory.bots.token_for(info.id)

    assert _run(scenario()) == "9001:" + "Q" * 35
    assert factory.supervisor.calls == [("restart", "active")]


def test_unlink_suspends_and_relink_resumes(tg_db):
    factory = _factory()
    factory.supervisor = FakeSupervisor()

    async def scenario():
        info = await _seed_bot(factory.bots)
        other = await _seed_bot(factory.bots, tg_id=2, owner_tg=555)
        await factory.suspend_for_unlink("u1")
        resumed = await factory.resume_after_link("u1", U1_TG)
        return resumed, await factory.bots.get(other.id), info

    resumed, other, info = _run(scenario())
    assert [b.id for b in resumed] == [info.id]
    # Creato da un altro account Telegram: resta sospeso.
    assert other.status == "suspended" and other.last_error == UNLINKED_REASON


def test_deleting_aion_user_revokes_assistants(tg_db):
    factory = _factory()
    api = FakeApi()

    async def scenario():
        acc = TelegramAccounts()
        code = await acc.create_pairing_code("u1", ttl_min=5)
        await acc.redeem_pairing_code(code.code, tg_user_id=U1_TG)
        info = await _seed_bot(factory.bots)
        await factory.purge_user(_bot(api), "u1")
        async with get_async_session_maker()() as s:
            links = (await s.execute(select(TgLink))).scalars().all()
        return await factory.bots.get(info.id), links

    info, links = _run(scenario())
    assert info.status == "deleted" and links == []
    assert len(api.of(ReplaceManagedBotToken)) == 1


def test_reconcile_recovers_and_detects_deleted_bots(tg_db):
    def broken():
        return FakeApi(me=CHILD, unauthorized=True)

    factory = _factory(child_api=broken)
    factory.supervisor = FakeSupervisor()

    class GoneApi(FakeApi):
        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, GetManagedBotToken):
                raise RuntimeError("Bad Request: bot not found")
            return await super().make_request(bot, method, timeout)

    api = GoneApi()

    async def scenario():
        info = await _seed_bot(factory.bots)
        summary = await factory.reconcile(_bot(api))
        return summary, await factory.bots.get(info.id)

    summary, info = _run(scenario())
    assert summary["gone"] == 1 and info.status == "deleted"
    assert "non esiste più" in api.texts()[0]


# ======================================================================
# Bot figli e supervisor
# ======================================================================
class ChildHarness:
    def __init__(self, accounts=None):
        self.api = FakeApi(me=CHILD)
        self.bot = _bot(self.api, CHILD_TOKEN)
        self.adapter = FakeAdapter()
        self.chat = ChatService(
            settings=_settings(rich_messages=False),
            adapter=self.adapter,
            sessions=FakeSessions(),
        )
        self.bots = TelegramBots()
        self.dp = build_child_dispatcher(
            accounts=accounts or FakeAccounts(),
            adapter=self.adapter,
            chat=self.chat,
            bots=self.bots,
        )
        self.n = 0

    async def send(self, text, user=OWNER):
        self.n += 1
        await self.dp.feed_update(
            self.bot,
            Update(
                update_id=self.n,
                message=_msg(self.n, chat_id=user.id, user=user, text=text),
            ),
        )
        await _drain(self.chat)

    async def group(self, text, user=OWNER, entities=None, reply_to_bot=False):
        self.n += 1
        reply = (
            _msg(
                999,
                chat_id=GROUP_ID,
                chat_type="supergroup",
                title="Vendite",
                user=CHILD,
                text="prima",
            )
            if reply_to_bot
            else None
        )
        msg = _msg(
            self.n,
            chat_id=GROUP_ID,
            chat_type="supergroup",
            title="Vendite",
            user=user,
            text=text,
            entities=entities,
            reply_to_message=reply,
        )
        await self.dp.feed_update(self.bot, Update(update_id=self.n, message=msg))
        await _drain(self.chat)

    async def added_by(self, user_id):
        self.n += 1
        me = User(id=CHILD.id, is_bot=True, first_name="RAG")
        event = ChatMemberUpdated(
            chat=Chat(id=GROUP_ID, type="supergroup", title="Vendite"),
            from_user=User(id=user_id, is_bot=False, first_name="X"),
            date=datetime.now(timezone.utc),
            old_chat_member=ChatMemberLeft(user=me),
            new_chat_member=ChatMemberMember(user=me),
        )
        await self.dp.feed_update(
            self.bot, Update(update_id=self.n, my_chat_member=event)
        )


def test_personal_assistant_answers_only_its_owner(tg_db):
    async def scenario():
        h = ChildHarness()
        await _seed_bot(h.bots, project="vendite")
        await h.send("quanto abbiamo venduto?")
        await h.send("e io?", user=COLLEAGUE)
        await h.bots.update(
            (await h.bots.get_by_tg_id(CHILD.id)).id, profile_slug="generic_assistant"
        )
        await h.send("di nuovo")
        return h

    h = _run(scenario())
    assert [(t[0], t[2], t[3]) for t in h.adapter.turns] == [
        ("u1", "rag", "vendite"),
        ("u1", "generic_assistant", "vendite"),
    ]
    assert any("personale" in t for t in h.api.texts())
    assert h.adapter.created[0][3] == {"telegram_bot": "rag_bot"}


def test_supervisor_follows_status_and_stops_on_401(tg_db):
    bots = TelegramBots()
    notes = []

    def supervisor(unauthorized=False):
        apis = []

        def make_bot(token, s):
            api = FakeApi(me=CHILD, unauthorized=unauthorized)
            apis.append(api)
            return _bot(api, token)

        async def notify(chat_id, text):
            notes.append(text)

        dp = build_child_dispatcher(
            accounts=FakeAccounts(), adapter=FakeAdapter(), chat=None, bots=bots
        )
        return BotSupervisor(
            bots=bots,
            dispatcher=dp,
            settings=_settings(polling_timeout=1),
            notify=notify,
            make_bot=make_bot,
        ), apis

    async def scenario():
        info = await _seed_bot(bots)
        sup, apis = supervisor()
        await sup.start_all()
        await asyncio.sleep(0.1)
        running = sup.is_running(CHILD.id)
        await sup.ensure(await bots.update(info.id, status=BotStatus.SUSPENDED))
        stopped = not sup.is_running(CHILD.id) and apis[0].closed
        await sup.stop_all()
        bad, _ = supervisor(unauthorized=True)
        await sup_ensure(bad, await bots.update(info.id, status=BotStatus.ACTIVE))
        return running, stopped, await bots.get(info.id)

    async def sup_ensure(sup, info):
        await sup.ensure(info)
        for _ in range(50):
            if not sup.is_running(CHILD.id):
                break
            await asyncio.sleep(0.02)

    running, stopped, info = _run(scenario())
    assert running and stopped
    assert info.status == "error" and "401" in info.last_error and notes


# ======================================================================
# Assistenti condivisi e gruppi
# ======================================================================
def _mention(text, username="@rag_bot"):
    return [
        MessageEntity(type="mention", offset=text.index(username), length=len(username))
    ]


def test_shared_assistant_uses_identity_of_who_writes(tg_db):
    async def scenario():
        h = ChildHarness()
        await _seed_bot(h.bots, mode="shared")
        await h.send("domanda di Ann")
        await h.send("domanda di Marco", user=COLLEAGUE)
        await h.send(
            "sconosciuto", user=User(id=STRANGER_TG, is_bot=False, first_name="X")
        )
        await h.send("/project", user=COLLEAGUE)
        return h

    h = _run(scenario())
    assert [(t[0], t[1]) for t in h.adapter.turns] == [
        ("u1", "domanda di Ann"),
        ("u2", "domanda di Marco"),
    ]
    texts = h.api.texts()
    assert (
        any("collega il tuo account" in t for t in texts)
        and "Solo il creatore" in texts[-1]
    )


def test_group_answers_only_when_addressed_with_shared_context(tg_db):
    async def scenario():
        h = ChildHarness()
        await _seed_bot(h.bots, mode="shared")
        await h.group("ciao a tutti")
        await h.group(
            "@rag_bot quanto abbiamo venduto?",
            entities=_mention("@rag_bot quanto abbiamo venduto?"),
        )
        await h.group("e a marzo?", user=COLLEAGUE, reply_to_bot=True)
        await h.group("/ask riassumi")
        return h

    h = _run(scenario())
    (u1, p1, *_), (u2, p2, *_), (u3, p3, *_) = h.adapter.turns
    assert (u1, u2, u3) == ("u1", "u2", "u1")
    assert (
        "«Vendite»" in p1
        and p1.endswith("quanto abbiamo venduto?")
        and "@rag_bot" not in p1
    )
    # Marco vede la domanda di Ann; Ann poi vede solo quella di Marco.
    assert (
        "Ann: quanto abbiamo venduto?" in p2
        and "Marco: e a marzo?" in p3
        and "Ann: quanto" not in p3
    )
    replies = [m for m in h.api.of(SendMessage) if m.chat_id == GROUP_ID]
    assert replies[0].reply_parameters is not None  # la risposta cita la domanda


def test_only_owner_adds_shared_assistant_to_groups(tg_db):
    async def scenario():
        h = ChildHarness()
        await _seed_bot(h.bots, mode="shared")
        await h.added_by(U2_TG)
        await h.added_by(U1_TG)
        personal = ChildHarness()
        await personal.bots.update(
            (await personal.bots.get_by_tg_id(CHILD.id)).id, mode="personal"
        )
        await personal.added_by(U1_TG)
        return h, personal

    h, personal = _run(scenario())
    assert len(h.api.of(LeaveChat)) == 1 and "Solo il creatore" in h.api.texts()[0]
    # Privacy mode e bot non amministratore: il benvenuto spiega /ask@bot.
    assert "/ask@rag_bot" in h.api.texts()[-1]
    assert len(personal.api.of(LeaveChat)) == 1


def test_group_uses_project_with_creator_permissions(tg_db):
    async def scenario():
        h = ChildHarness()
        await _seed_bot(h.bots, mode="shared", project="vendite")
        await h.group("/ask quanto abbiamo venduto?", user=COLLEAGUE)
        await h.send(
            "quanto abbiamo venduto?", user=COLLEAGUE
        )  # in privato: controllo per persona
        return h

    h = _run(scenario())
    [turn] = h.adapter.turns
    assert (turn[0], turn[3], turn[5]) == ("u2", "vendite", "user-u1")
    assert any("non accessibile" in t for t in h.api.texts())


def test_project_access_delegation_is_scoped_to_conversation_and_turn():
    from src.runtime import project_access_delegation as d
    from src.runtime.sql_query_memory_context import (
        clear_sql_qm_turn_context,
        get_sql_qm_turn_context,
        set_sql_qm_turn_context,
    )

    assert d.project_user("c1", "anna", "vendite") == "anna"
    with d.delegated("c1", "Vendite", "creatore"):
        assert d.project_user("c1", "anna", "vendite") == "creatore"
        assert d.project_user("c1", "anna", "altro") == "anna"
        assert d.project_user("c2", "anna", "vendite") == "anna"
        set_sql_qm_turn_context(
            user_id="anna", profile_slug="p", project_slug="vendite", session_id="c1"
        )
    assert d.project_user("c1", "anna", "vendite") == "anna"
    try:
        assert get_sql_qm_turn_context("c1").user_id == "creatore"
    finally:
        clear_sql_qm_turn_context("c1")


# ======================================================================
# Amministrazione
# ======================================================================
def test_admin_settings_mask_secrets():
    from src.api import settings_api

    for key in ("AION_TELEGRAM_MANAGER_TOKEN", "AION_CREDENTIAL_ENCRYPTION_KEY"):
        assert settings_api._mask_settings_for_get({key: "segreto"}) == {key: "***"}
    assert not settings_api._is_sensitive_env_key("AION_CHAT_MAX_TOKENS")
    assert settings_api._telegram_changed(
        {"AION_TELEGRAM_ENABLED": "1"}, {"AION_TELEGRAM_ENABLED": "0"}
    )


@pytest.fixture()
def admin_client(tg_db, monkeypatch):  # noqa: F811
    from src.api import admin_telegram

    for key in [k for k in __import__("os").environ if k.startswith("AION_TELEGRAM_")]:
        monkeypatch.delenv(key)
    settings = _settings(max_bots_per_user=3)
    monkeypatch.setattr(admin_telegram, "get_telegram_settings", lambda: settings)
    monkeypatch.setattr(tg_config, "get_telegram_settings", lambda: settings)
    runtime.set_gateway(None)
    app = FastAPI()
    app.include_router(admin_telegram.router, prefix="/admin")
    with TestClient(app) as c:
        yield c


def test_admin_bot_actions_and_reassign(admin_client):
    bots = TelegramBots()

    async def seed():
        info = await _seed_bot(bots, mode="shared")
        await bots.update(
            info.id,
            status=BotStatus.SUSPENDED,
            last_error=OWNER_CHANGED_REASON,
            pending_owner_tg_user_id=U2_TG,
        )
        return info

    info = _run(seed())
    [listed] = admin_client.get("/admin/telegram/bots").json()["data"]
    assert (
        listed["owner"]["identifier"] == "user-u1"
        and "token" not in json.dumps(listed).lower()
    )
    # Il nuovo proprietario deve aver collegato Telegram ad AION.
    r = admin_client.post(f"/admin/telegram/bots/{info.id}/reassign")
    assert r.json()["detail"]["code"] == "new_owner_not_linked"

    async def link():
        acc = TelegramAccounts()
        code = await acc.create_pairing_code("u2", ttl_min=5)
        await acc.redeem_pairing_code(code.code, tg_user_id=U2_TG)

    _run(link())
    assert (
        admin_client.post(f"/admin/telegram/bots/{info.id}/reassign").json()["status"]
        == "active"
    )
    assert _run(bots.get(info.id)).owner_aion_user_id == "u2"
    assert (
        admin_client.post(f"/admin/telegram/bots/{info.id}/suspend").json()["status"]
        == "suspended"
    )
    r = admin_client.post(f"/admin/telegram/bots/{info.id}/delete").json()
    assert r == {
        "ok": True,
        "status": "deleted",
        "revoked": False,
    }  # senza gateway: niente revoca
    actions = {
        a["action"] for a in admin_client.get("/admin/telegram/audit").json()["data"]
    }
    assert {"bot_owner_reassigned", "bot_suspended_admin", "bot_deleted"} <= actions


def test_admin_quota_per_user(admin_client):
    bots = TelegramBots()
    _run(_seed_bot(bots))
    assert (
        admin_client.put("/admin/telegram/quotas/u1", json={"max_bots": 0}).json()[
            "max_bots"
        ]
        == 0
    )
    assert (
        admin_client.put(
            "/admin/telegram/quotas/u1", json={"max_bots": 999}
        ).status_code
        == 422
    )
    factory = BotFactory(
        bots=bots, accounts=None, adapter=None, settings=_settings(max_bots_per_user=3)
    )
    with pytest.raises(QuotaExceeded):
        _run(factory.check_quota("u1"))
    admin_client.put("/admin/telegram/quotas/u1", json={"max_bots": None})
    _run(factory.check_quota("u1"))  # di nuovo la quota predefinita


def test_test_token_never_uses_real_env_token(admin_client):
    assert admin_client.post(
        "/admin/telegram/test-token", json={"token": "***"}
    ).json() == {"ok": False, "error": "missing"}
    assert (
        admin_client.post("/admin/telegram/test-token", json={"token": "x"}).json()[
            "error"
        ]
        == "malformed"
    )


def test_channel_policy_blocks_profiles_and_projects(monkeypatch):
    from src.channels.telegram import adapter as adapter_mod
    from src.channels.telegram.adapter import AionAdapter, ChannelPolicyError

    settings = _settings(blocked_profiles="Posta", blocked_projects="hr")
    monkeypatch.setattr(adapter_mod, "_policy", lambda: settings)
    user = AionUserRef(row_id="u1", identifier="user-u1")
    with pytest.raises(ChannelPolicyError):
        _run(AionAdapter().check_project(user, "HR", "rag"))

    from src.agent_profile import profile_manager

    class P:
        slug = "posta"

    monkeypatch.setattr(profile_manager, "resolve_profile", lambda name: P())
    with pytest.raises(ChannelPolicyError):
        _run(AionAdapter().resolve_profile(user, "posta"))


def test_telegram_chats_are_read_only_via_api(tg_db):
    from src.api.v1.chat import _reject_read_only_conversation

    async def scenario():
        async with get_async_session_maker()() as s:
            for cid, meta in (("tg", {"source": "telegram"}), ("web", {})):
                s.add(
                    Conversation(
                        id=cid,
                        tenant_id="default",
                        user_id="user-u1",
                        profile_slug="aion_std",
                        message_count=0,
                        metadata_json=json.dumps(meta),
                    )
                )
            await s.commit()
        await _reject_read_only_conversation("web")
        await _reject_read_only_conversation("nuova")
        with pytest.raises(HTTPException) as exc:
            await _reject_read_only_conversation("tg")
        return exc.value

    err = _run(scenario())
    assert err.status_code == 409 and err.detail["code"] == "telegram_read_only"


def test_schema_upgrade_adds_new_columns_to_old_tables():
    from src.channels.telegram.models import _add_missing_columns

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tg_bots (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO tg_bots (id) VALUES (1)")
        _add_missing_columns(conn)
        _add_missing_columns(conn)
        assert conn.exec_driver_sql("SELECT mode FROM tg_bots").scalar() == "personal"
