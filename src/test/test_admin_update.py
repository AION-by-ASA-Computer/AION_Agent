"""Tests for the one-click upgrade proxy (``src/api/admin_update.py``) and its
use in ``/admin/version-check`` (``src/api/version_check.py``).

The aion-updater sidecar is replaced by an ``httpx.MockTransport``; admin auth
is overridden and the audit writer is captured, so no DB or network is needed.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import admin_update, version_check
from src.api.auth_login import ChatAuthIdentity, require_admin_role

PLAN = {
    "current": "1.6.2",
    "target": "1.7.0",
    "latest_release": "1.7.0",
    "chain": ["1.6.3", "1.7.0"],
    "update_available": True,
    "mode": "github",
}


@pytest.fixture
def audit_calls(monkeypatch) -> List[Dict[str, Any]]:
    """Capture record_admin_action calls instead of writing to the DB."""
    calls: List[Dict[str, Any]] = []

    async def fake_record(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(admin_update, "record_admin_action", fake_record)
    return calls


@pytest.fixture
def sidecar(monkeypatch):
    """Install a fake sidecar: returns a setter for the request handler.

    Every request seen by the fake is appended to ``seen`` for assertions.
    """
    monkeypatch.setenv("AION_UPDATER_TOKEN", "secret-token")
    monkeypatch.setenv("AION_UPDATER_URL", "http://updater:8090")
    state: Dict[str, Any] = {"handler": None, "seen": []}

    def transport_handler(request: httpx.Request) -> httpx.Response:
        state["seen"].append(request)
        return state["handler"](request)

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(admin_update.httpx, "AsyncClient", client_factory)

    def set_handler(fn: Callable[[httpx.Request], httpx.Response]) -> Dict[str, Any]:
        state["handler"] = fn
        return state

    return set_handler


@pytest.fixture
def client() -> TestClient:
    """App with only the update router and an admin identity."""
    app = FastAPI()
    app.include_router(admin_update.router)
    app.include_router(version_check.router, prefix="/admin")
    app.dependency_overrides[require_admin_role] = lambda: ChatAuthIdentity(
        identifier="alice", via="chat_token", roles=["admin"]
    )
    version_check._cache.clear()
    return TestClient(app)


def test_status_unsupported_without_token(client, monkeypatch):
    """No AION_UPDATER_TOKEN: status says unsupported instead of failing."""
    monkeypatch.delenv("AION_UPDATER_TOKEN", raising=False)
    res = client.get("/admin/update/status")
    assert res.status_code == 200
    assert res.json() == {"supported": False, "reason": "not_configured"}


def test_status_unsupported_when_unreachable(client, sidecar):
    """Network error towards the sidecar maps to supported=false/unreachable."""

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    sidecar(boom)
    res = client.get("/admin/update/status")
    assert res.json() == {"supported": False, "reason": "unreachable"}


def test_status_proxied_with_bearer(client, sidecar):
    """Status is proxied as-is and the shared token is sent as Bearer."""
    state = sidecar(lambda r: httpx.Response(200, json={"supported": True, "state": "idle"}))
    res = client.get("/admin/update/status")
    assert res.json() == {"supported": True, "state": "idle"}
    req = state["seen"][0]
    assert req.url == "http://updater:8090/status"
    assert req.headers["authorization"] == "Bearer secret-token"


def test_plan_adds_release_links_and_refresh(client, sidecar):
    """Plan gets per-hop release links; `local` has none; refresh is forwarded."""
    plan = {**PLAN, "chain": ["1.7.0", "local"], "target": "local", "mode": "hybrid-local"}
    state = sidecar(lambda r: httpx.Response(200, json=plan))
    res = client.get("/admin/update/plan?refresh=true")
    assert res.status_code == 200
    assert res.json()["hops"] == [
        {
            "version": "1.7.0",
            "release_url": "https://github.com/AION-by-ASA-Computer/AION_Agent/releases/tag/v1.7.0",
        },
        {"version": "local", "release_url": None},
    ]
    assert state["seen"][0].url.params.get("refresh") == "1"


def test_plan_unavailable_is_503(client, monkeypatch):
    """Without a configured sidecar /plan answers 503 updater_not_configured."""
    monkeypatch.delenv("AION_UPDATER_TOKEN", raising=False)
    res = client.get("/admin/update/plan")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "updater_not_configured"


def test_start_proxies_and_audits(client, sidecar, audit_calls):
    """Successful start returns 202, forwards requested_by and writes the audit row."""
    started = {**PLAN, "state": "running", "phase": "starting"}
    state = sidecar(lambda r: httpx.Response(202, json=started))
    res = client.post("/admin/update/start")
    assert res.status_code == 202
    assert res.json()["state"] == "running"
    assert json.loads(state["seen"][0].content) == {"requested_by": "alice"}
    assert len(audit_calls) == 1
    audit = audit_calls[0]
    assert audit["operation"] == "update.start"
    assert audit["actor"] == "alice"
    assert audit["resource_id"] == "1.7.0"
    assert audit["payload"]["chain"] == ["1.6.3", "1.7.0"]


@pytest.mark.parametrize(
    "sidecar_status,code,expected_status",
    [
        (409, "upgrade_running", 409),
        (404, "no_update", 404),
        (502, "plan_failed", 502),
        (500, "internal", 502),
    ],
)
def test_start_errors_propagated(client, sidecar, audit_calls, sidecar_status, code, expected_status):
    """409/404 pass through, other sidecar errors become 502; no audit on failure."""
    sidecar(lambda r: httpx.Response(sidecar_status, json={"error": code, "detail": "msg"}))
    res = client.post("/admin/update/start")
    assert res.status_code == expected_status
    assert res.json()["detail"] == {"code": code, "message": "msg"}
    assert audit_calls == []


def test_start_unavailable_is_503(client, sidecar, audit_calls):
    """Unreachable sidecar on start → 503 updater_unreachable, nothing audited."""

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    sidecar(boom)
    res = client.post("/admin/update/start")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "updater_unreachable"
    assert audit_calls == []


def test_version_check_uses_sidecar_plan(client, sidecar, monkeypatch):
    """With the sidecar, version-check reports its plan and self_update_supported."""

    async def no_github():  # must not be called when the sidecar answers
        raise AssertionError("GitHub fallback used")

    monkeypatch.setattr(version_check, "_fetch_latest_release", no_github)
    sidecar(lambda r: httpx.Response(200, json=PLAN))
    res = client.get("/admin/version-check")
    assert res.status_code == 200
    body = res.json()
    assert body["current"] == "1.6.2"
    assert body["latest"] == "1.7.0"
    assert body["update_available"] is True
    assert body["self_update_supported"] is True
    assert body["update_mode"] == "github"


def test_version_check_falls_back_to_github(client, monkeypatch):
    """Without the sidecar, version-check keeps the GitHub-based behaviour."""
    monkeypatch.delenv("AION_UPDATER_TOKEN", raising=False)
    monkeypatch.setenv("AION_VERSION", "1.6.2")

    async def latest():
        return "1.7.0"

    monkeypatch.setattr(version_check, "_fetch_latest_release", latest)
    body = client.get("/admin/version-check").json()
    assert body["update_available"] is True
    assert body["self_update_supported"] is False
