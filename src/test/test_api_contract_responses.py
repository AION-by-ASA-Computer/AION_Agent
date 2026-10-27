"""Snapshot delle risposte JSON delle route del contratto (``src/api/contract.py``).

Le fixture in ``src/test/fixtures/contract/`` fissano la forma esatta delle
risposte: chiavi presenti o assenti, ``null``, formato delle date. Un cambio
deve essere voluto: rigenerarle con ``AION_UPDATE_CONTRACT_FIXTURES=1``.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db
from src.test.test_api_keys import _make_user

FIXTURES = Path(__file__).parent / "fixtures" / "contract"
USER = "sre-bot"
CONV = "conv-contract"

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?P<frac>\.\d+)?(?P<tz>Z|[+-]\d{2}:\d{2})?$"
)


def _shape(value: Any) -> Any:
    """Sostituisce id generati e timestamp con un segnaposto che ne tiene il formato."""
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shape(v) for v in value]
    if isinstance(value, str):
        if _UUID_RE.match(value):
            return "<uuid>"
        m = _ISO_RE.match(value)
        if m:
            frac = "frac" if m.group("frac") else "nofrac"
            return f"<iso:{frac}:{m.group('tz') or 'naive'}>"
    if isinstance(value, float):
        return "<float>"
    return value


def _check(name: str, payload: Any) -> None:
    path = FIXTURES / f"{name}.json"
    shaped = _shape(payload)
    if os.getenv("AION_UPDATE_CONTRACT_FIXTURES") == "1" or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(shaped, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert shaped == expected, f"risposta di {name} diversa dalla fixture"


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    asyncio.run(_reset_unified_db(monkeypatch, tmp_path))
    monkeypatch.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_ADMIN_PASSWORD_AUTH", "1")
    monkeypatch.setenv("AION_SETUP_ADMIN_BOOTSTRAP", "0")
    monkeypatch.setenv("AION_CHAT_AUTH_SECRET", "s" * 40)

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "contract_profile.yaml").write_text(
        "name: Contract Profile\n"
        "description: Profilo per i test del contratto\n"
        "instructions: Test.\n"
        "skills: []\n"
        "mcp_servers: []\n",
        encoding="utf-8",
    )
    import src.main as agent_main
    from src.api.auth_login import issue_chat_token
    from src.api.main import app

    # Il lifespan registra il loop del TestClient come loop globale; senza
    # ripristino i test successivi userebbero un loop chiuso.
    monkeypatch.setattr(agent_main, "_GLOBAL_LOOP", agent_main._GLOBAL_LOOP)
    with TestClient(app) as c:
        # Dopo il lifespan, che ricarica i profili da config/profiles.
        from src.agent_profile import profile_manager

        for attr in ("std_path", "write_path", "base_path"):
            monkeypatch.setattr(profile_manager, attr, profiles_dir)
        profile_manager.load_all()
        uid = c.portal.call(lambda: _make_user(USER, can_keys=True))
        token = issue_chat_token(user_row_id=uid, user_identifier=USER)
        res = c.post(
            "/v1/me/api-keys",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": "contract",
                "scopes": ["chat", "conversations:read", "conversations:write"],
                "expires_in_days": 30,
            },
        )
        assert res.status_code == 201, res.text
        c.headers["X-Api-Key"] = res.json()["key"]
        c.portal.call(_seed)
        yield c


async def _seed() -> None:
    from sqlalchemy import update

    from src.data.engine import get_async_session_maker
    from src.data.history_bridge import UnifiedHistoryBridge
    from src.data.models import Message

    bridge = UnifiedHistoryBridge()
    await bridge.add_message(
        CONV, "user", "Analizza l'allarme", user_id=USER, message_id="m-user-1"
    )
    await bridge.add_message(
        CONV,
        "assistant",
        "Prima risposta, poi archiviata.",
        user_id=USER,
        message_id="m-asst-archived",
        metadata_json=json.dumps({"sre_author": "mario.rossi"}),
    )
    await bridge.add_message(
        CONV, "user", "Continua", user_id=USER, message_id="m-user-2"
    )
    await bridge.add_message(
        CONV,
        "assistant",
        "Risposta con timeline salvata.",
        user_id=USER,
        reasoning="Controllo i log.",
        message_id="m-asst-timeline",
        timeline_json=json.dumps(
            [
                {"kind": "reasoning", "id": "r1", "content": "Controllo i log."},
                {
                    "kind": "tool",
                    "id": "t1",
                    "name": "splunk_search",
                    "input": {"q": "error"},
                    "output": "3 risultati",
                    "status": "done",
                    "isError": False,
                    "tokens_in": 10,
                    "tokens_out": 20,
                },
                {
                    "kind": "text",
                    "id": "x1",
                    "content": "Risposta con timeline salvata.",
                },
            ]
        ),
    )
    await bridge.add_message(
        CONV, "user", "Riassumi", user_id=USER, message_id="m-user-3"
    )
    await bridge.add_message(
        CONV,
        "assistant",
        "Risposta con timeline ricostruita.",
        user_id=USER,
        reasoning="Leggo il file.",
        message_id="m-asst-legacy",
    )
    await bridge.add_step(
        CONV,
        name="sandbox_read_file",
        type="tool",
        input='{"path":"a.txt"}',
        output="contenuto",
        message_id="m-asst-legacy",
        metadata_json='{"duration_ms": 12}',
    )
    await bridge.add_attachment(
        CONV,
        storage_key="workspace/report.md",
        original_name="report.md",
        mime="text/markdown",
        size_bytes=128,
        kind="artifact",
        message_id="m-asst-legacy",
    )
    async with get_async_session_maker()() as session:
        await session.execute(
            update(Message)
            .where(Message.id == "m-asst-archived")
            .values(archived_reason="mid_turn_compaction", archived_at=_now())
        )
        await session.commit()


def _now():
    from datetime import datetime

    return datetime(2026, 10, 26, 9, 30, 0)


def test_contract_responses_match_fixtures(client):
    res = client.post(
        "/v1/conversations",
        json={
            "profile": "contract_profile",
            "title": "INC0012345",
            "metadata": {"incident": "INC0012345"},
            "tags": ["sre", "checkmk"],
        },
    )
    assert res.status_code == 200, res.text
    _check("post_v1_conversations", res.json())

    res = client.post("/v1/conversations", json={"profile": "contract_profile"})
    assert res.status_code == 200, res.text
    _check("post_v1_conversations_minimal", res.json())

    res = client.get(f"/chat-ui/conversations/{CONV}/messages")
    assert res.status_code == 200, res.text
    _check("get_chat_ui_messages", res.json())

    res = client.get("/chat-ui/conversations/does-not-exist/messages")
    assert res.status_code == 200, res.text
    _check("get_chat_ui_messages_missing", res.json())

    res = client.get(f"/chat-ui/conversations/{CONV}/stream-status")
    assert res.status_code == 200, res.text
    _check("get_chat_ui_stream_status_inactive", res.json())

    from src.runtime.redis_client import redis_set_stream_active

    client.portal.call(
        lambda: redis_set_stream_active(
            CONV,
            assistant_message_id="m-asst-next",
            user_message_id="m-user-next",
            profile_name="contract_profile",
        )
    )
    res = client.get(f"/chat-ui/conversations/{CONV}/stream-status")
    assert res.status_code == 200, res.text
    _check("get_chat_ui_stream_status_active", res.json())

    res = client.post(
        f"/chat-ui/conversations/{CONV}/messages/m-asst-legacy/rate",
        json={"rating": 1, "comment": "utile"},
    )
    assert res.status_code == 200, res.text
    _check("post_chat_ui_rate", res.json())

    from src.chart_queue import chart_queue

    chart_queue.push_serialized(
        CONV,
        {
            "query": "up",
            "data": [{"index": 0, "value": 1}],
            "chart_kind": "line",
            "x_key": "index",
        },
    )
    res = client.get(f"/sessions/{CONV}/charts")
    assert res.status_code == 200, res.text
    _check("get_sessions_charts", res.json())

    res = client.get(f"/v1/conversations/{CONV}/steps")
    assert res.status_code == 200, res.text
    _check("get_v1_conversation_steps", res.json())

    res = client.post(f"/v1/chat/stop?conversation_id={CONV}")
    assert res.status_code == 200, res.text
    _check("post_v1_chat_stop", res.json())

    res = client.get("/profiles")
    assert res.status_code == 200, res.text
    _check("get_profiles", res.json())
