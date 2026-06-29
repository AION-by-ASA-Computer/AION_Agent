"""LLM health ping is cached within TTL."""

from unittest.mock import patch

from src.runtime.llm_health import check_llm_connection, reset_llm_health_cache


def test_llm_health_cached_within_ttl(monkeypatch):
    reset_llm_health_cache()
    monkeypatch.setenv("AION_LLM_HEALTH_CACHE_SEC", "60")
    calls = {"n": 0}

    def _fake_get(*_a, **_k):
        calls["n"] += 1
        return type("R", (), {"status_code": 200})()

    with patch("src.runtime.llm_health.requests.get", side_effect=_fake_get):
        ok1, _ = check_llm_connection("http://llm.test/v1", "")
        ok2, _ = check_llm_connection("http://llm.test/v1", "")
    assert ok1 and ok2
    assert calls["n"] == 1
