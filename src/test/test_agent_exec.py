"""Tests for async vs legacy agent execution wrapper."""

import asyncio
import inspect
import json
import threading
import types

from src.agent_pipeline import (
    haystack_agent_streaming_callback,
    haystack_agent_streaming_callback_async,
)
from src.runtime import agent_exec


def test_haystack_streaming_callbacks_async_compatible():
    assert not inspect.iscoroutinefunction(haystack_agent_streaming_callback)
    assert inspect.iscoroutinefunction(haystack_agent_streaming_callback_async)


def test_json_recovery_proxy_does_not_mutate_stdlib_json():
    """The Haystack JSON recovery patch must not replace the stdlib json.loads globally.

    After importing src.main the real json.loads should still be the C-extension
    implementation (not our recovery wrapper) so that concurrent callers are unaffected.
    """
    import src.aion_env  # noqa: F401

    import haystack.components.generators.utils as _gen_utils

    # The proxy must NOT be the real json module (it should be a SimpleNamespace).
    assert not isinstance(_gen_utils.json, types.ModuleType), (
        "_gen_utils.json should be a SimpleNamespace proxy, not the real json module. "
        "The patch in src/main.py must run at import time."
    )

    # The stdlib json.loads must still work normally (not replaced globally).
    assert json.loads('{"a": 1}') == {"a": 1}, "stdlib json.loads broken"

    # The proxy's loads should handle valid JSON correctly too.
    recovery_fn = getattr(_gen_utils.json, "loads", None)
    assert recovery_fn is not None, "_gen_utils.json proxy missing loads attribute"
    assert recovery_fn('{"x": 2}') == {"x": 2}, "proxy json.loads broken for valid JSON"

    # The proxy's loads must NOT be the same object as stdlib json.loads
    # (confirming our recovery wrapper was installed on the proxy).
    assert recovery_fn is not json.loads, (
        "proxy loads should be the recovery wrapper, not the original json.loads"
    )


def test_json_recovery_concurrent_calls_no_interference():
    """Recovery wrapper must not interfere with concurrent json.loads calls in other threads."""
    import src.aion_env  # noqa: F401
    import src.main  # ensure patch is applied

    errors: list[Exception] = []
    results: list[object] = []
    lock = threading.Lock()

    def _worker(idx: int) -> None:
        try:
            # Each thread calls the real stdlib json.loads independently.
            val = json.loads(f'{{"idx": {idx}}}')
            with lock:
                results.append(val)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent json.loads raised errors: {errors}"
    assert len(results) == 20
    idxs = sorted(r["idx"] for r in results)
    assert idxs == list(range(20))


def test_run_agent_turn_uses_async_runner_by_default(monkeypatch):
    monkeypatch.setenv("AION_AGENT_EXEC_LEGACY_THREAD", "0")

    def dummy_clear():
        pass

    agent_exec.legacy_thread_execution_enabled.cache_clear = dummy_clear

    async def _async_runner(msgs):
        return ("async", len(msgs))

    def _sync_runner(msgs):
        return ("sync", len(msgs))

    out = asyncio.run(
        agent_exec.run_agent_turn(
            ["m"],
            sync_runner=_sync_runner,
            async_runner=_async_runner,
        )
    )
    assert out == ("async", 1)


def test_run_agent_turn_legacy_thread(monkeypatch):
    monkeypatch.setenv("AION_AGENT_EXEC_LEGACY_THREAD", "1")

    async def _async_runner(msgs):
        return "async"

    def _sync_runner(msgs):
        return "sync"

    out = asyncio.run(
        agent_exec.run_agent_turn(
            ["m"],
            sync_runner=_sync_runner,
            async_runner=_async_runner,
        )
    )
    assert out == "sync"
