import asyncio


def test_redis_drain_degrades_once_on_connection_error(monkeypatch):
    import src.runtime.redis_client as rc

    async def run():
        rc._client = None
        rc._fallback_used = False
        rc._redis_degraded = False
        rc._redis_warn_once_keys.clear()

        class BrokenRedis:
            async def lpop(self, _key: str):
                raise ConnectionError(
                    "Error 61 connecting to localhost:6379. Connection refused."
                )

        monkeypatch.setenv("AION_REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("AION_REDIS_FALLBACK_LOCAL", "1")
        rc._client = BrokenRedis()

        out = await rc.redis_drain_session_events("sess-1", max_items=3)
        assert out == []
        assert rc.redis_using_fallback() is True
        assert isinstance(rc.get_redis(), rc._LocalFallback)

        out2 = await rc.redis_drain_session_events("sess-1", max_items=3)
        assert out2 == []

    asyncio.run(run())
