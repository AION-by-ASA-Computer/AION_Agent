"""Tests for in-flight /chat stream markers (client reconnect)."""

import pytest

from src.runtime.redis_client import (
    redis_clear_stream_active,
    redis_get_stream_active,
    redis_set_stream_active,
)


@pytest.mark.anyio
async def test_stream_active_roundtrip(monkeypatch):
    store: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, ex=None):
            store[key] = value

        async def get(self, key):
            return store.get(key)

        async def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr("src.runtime.redis_client.get_redis", lambda: FakeRedis())

    await redis_set_stream_active(
        "conv-1",
        assistant_message_id="aid-1",
        user_message_id="uid-1",
        profile_name="generic",
    )
    meta = await redis_get_stream_active("conv-1")
    assert meta is not None
    assert meta["assistant_message_id"] == "aid-1"
    assert meta["user_message_id"] == "uid-1"
    assert meta["profile_name"] == "generic"
    assert "started_at" in meta

    await redis_clear_stream_active("conv-1")
    assert await redis_get_stream_active("conv-1") is None
