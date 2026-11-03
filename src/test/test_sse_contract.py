"""Contratto degli eventi SSE di ``/v1/chat/stream`` (``src/api/v1/sse_schema.py``).

- ``fixtures/sse/chat_stream_basic.txt``: trascrizione del wire di un turno con
  token, un tool call e la risposta finale. Rigenerarla con
  ``AION_UPDATE_CONTRACT_FIXTURES=1`` quando cambia volutamente il formato.
- Lo stesso turno viene eseguito dal vivo (agente finto, nessun LLM): ogni
  evento emesso deve essere un ``ChatStreamEvent``, così un nuovo ``type`` non
  modellato fa fallire il test.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.api.v1.sse_schema import SseStreamErrorFrame, chat_stream_event_adapter
from src.test.test_api_contract_responses import CONV, client  # noqa: F401

FIXTURE = Path(__file__).parent / "fixtures" / "sse" / "chat_stream_basic.txt"
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _frames(raw: str) -> List[Tuple[str, Any]]:
    """Frame SSE come ``(event, data)``; i commenti diventano ``(":", testo)``."""
    frames: List[Tuple[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n", raw.strip()):
        event, data = "message", []
        for line in block.splitlines():
            if line.startswith(":"):
                frames.append((":", line[1:].strip()))
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            frames.append((event, json.loads("\n".join(data))))
    return frames


def _check_turn(frames: List[Tuple[str, Any]]) -> List[str]:
    """Valida ogni frame e restituisce i ``type`` nell'ordine."""
    types = []
    for event, data in frames:
        if event == ":":
            continue
        if event == "error":
            SseStreamErrorFrame.model_validate(data)
            types.append("<event:error>")
            continue
        assert event == "message", event
        try:
            chat_stream_event_adapter.validate_python(data)
        except ValidationError as exc:
            raise AssertionError(f"evento non nel contratto: {data}\n{exc}") from exc
        types.append(data["type"])
    return types


def test_recorded_stream_matches_schema():
    frames = _frames(FIXTURE.read_text(encoding="utf-8"))
    assert frames[0] == (":", "aion-open")
    types = _check_turn(frames)
    assert types[0] == "turn_started"
    assert types[-1] == "final"
    assert {"token", "tool_event", "stream_end"} <= set(types)


def test_error_frame_schema():
    SseStreamErrorFrame.model_validate(
        {"error": "x", "code": "profile_not_found", "available_slugs": ["a"]}
    )
    with pytest.raises(ValidationError):
        chat_stream_event_adapter.validate_python({"type": "not_a_type"})


def _fake_agent():
    from haystack.dataclasses import ChatMessage, StreamingChunk

    from src.runtime.tool_events import tool_event_bus

    async def run_async(messages, streaming_callback=None, **_kwargs):
        tool_event_bus.put_event(
            CONV,
            {
                "type": "tool_start",
                "id": "call-1",
                "name": "splunk_search",
                "input": {"q": "error"},
            },
        )
        tool_event_bus.put_event(
            CONV,
            {
                "type": "tool_end",
                "id": "call-1",
                "name": "splunk_search",
                "output": "3 risultati",
                "input": {"q": "error"},
            },
        )
        # Lascia al listener della pipeline il tempo di inoltrare gli eventi tool.
        await asyncio.sleep(0.1)
        for piece in ("Trovati ", "3 errori."):
            await streaming_callback(StreamingChunk(content=piece))
        await streaming_callback(StreamingChunk(content="", finish_reason="stop"))
        return {
            "messages": [*messages, ChatMessage.from_assistant("Trovati 3 errori.")]
        }

    agent = MagicMock()
    agent.run_async = run_async
    agent.system_prompt = ""
    agent.tools = []
    agent.max_agent_steps = 5
    return agent


def test_live_stream_matches_schema(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("AION_API_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("AION_LTM_EXTRACT", "0")
    monkeypatch.setenv("AION_LTM_RETRIEVAL", "0")
    with (
        patch(
            "src.api.v1.chat.get_agent",
            new=AsyncMock(return_value=(_fake_agent(), "contract_profile")),
        ),
        patch("src.runtime.llm_health.check_llm_connection", return_value=(True, None)),
    ):
        with client.stream(
            "POST",
            "/v1/chat/stream",
            json={
                "conversation_id": CONV,
                "profile": "contract_profile",
                "message": "Cerca gli errori",
            },
        ) as res:
            assert res.status_code == 200
            assert res.headers["content-type"].startswith("text/event-stream")
            raw = res.read().decode()

    frames = _frames(raw)
    types = _check_turn(frames)
    assert types[0] == "turn_started", types
    assert types[-1] == "final", types
    tool_types = [
        d["event"]["type"]
        for e, d in frames
        if e == "message" and d["type"] == "tool_event"
    ]
    assert tool_types == ["tool_start", "tool_end"]

    if os.getenv("AION_UPDATE_CONTRACT_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(_render(frames), encoding="utf-8")


def _render(frames: List[Tuple[str, Any]]) -> str:
    """Wire format per la fixture: id generati e snapshot del prompt abbreviati."""
    out = []
    for event, data in frames:
        if event == ":":
            out.append(f": {data}\n\n")
            continue
        if data.get("type") == "prompt_snapshot":
            data = {**data, "snapshot": {"phase": data["snapshot"].get("phase")}}
        line = _UUID_RE.sub("<uuid>", json.dumps(data, ensure_ascii=False))
        out.append(f"event: {event}\ndata: {line}\n\n")
    return "".join(out)
