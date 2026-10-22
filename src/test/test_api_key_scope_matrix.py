"""Matrice API key x scope su tutte le route dell'app (in-process).

Riusa ``scripts/security/check_api_key_scopes.py``: stessa mappa
``EXPECTED_SCOPE`` e stessa classificazione delle risposte, ma con
``TestClient`` al posto del backend in esecuzione.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.test.test_api_endpoints import _reset_unified_db
from src.test.test_api_keys import _make_user

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "security"
    / "check_api_key_scopes.py"
)
_spec = importlib.util.spec_from_file_location("check_api_key_scopes", _SCRIPT)
matrix = importlib.util.module_from_spec(_spec)
# dataclass risolve le annotazioni tramite sys.modules[__module__]
sys.modules[_spec.name] = matrix
_spec.loader.exec_module(matrix)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    asyncio.run(_reset_unified_db(mp, tmp_path_factory.mktemp("scope_matrix")))
    mp.setenv("AION_CHAT_PASSWORD_AUTH", "1")
    mp.setenv("AION_ADMIN_PASSWORD_AUTH", "1")
    mp.setenv("AION_SETUP_ADMIN_BOOTSTRAP", "0")
    mp.setenv("AION_CHAT_AUTH_SECRET", "s" * 40)

    from src.api.auth_login import issue_chat_token
    from src.api.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        uid = client.portal.call(
            lambda: _make_user(
                "matrix", can_keys=True, max_keys=len(matrix.KEY_SCOPES), ttl=7
            )
        )
        token = issue_chat_token(user_row_id=uid, user_identifier="matrix")
        keys = {}
        for label, scopes in matrix.KEY_SCOPES.items():
            res = client.post(
                "/v1/me/api-keys",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": label, "scopes": list(scopes), "expires_in_days": 1},
            )
            assert res.status_code == 201, res.text
            keys[label] = res.json()["key"]

        def send(method, path, headers, body):
            res = client.request(
                method, path, headers=headers, content=body, follow_redirects=False
            )
            return res.status_code, res.content

        yield {
            "send": send,
            "keys": keys,
            "ops": matrix.operations_from_app(app),
        }
    mp.undo()


def test_expected_scope_map_matches_app(env):
    assert matrix.stale_expectations(env["ops"]) == []


def test_every_operation_respects_scopes(env):
    findings = matrix.run_matrix(env["send"], env["ops"], env["keys"])
    bad = [
        f"{f.verdict} {f.method} {f.path}: {f.detail}"
        for f in findings
        if f.verdict not in ("OK", "PUBLIC")
    ]
    assert bad == []
    scoped = [f for f in findings if f.scope]
    assert len(scoped) == len(matrix.EXPECTED_SCOPE)


@pytest.mark.parametrize(
    ("op", "scope", "verdict"),
    [
        # endpoint con scope tolto dalla mappa: la chiave entra -> LEAK
        (("GET", "/profiles"), None, "LEAK"),
        # scope sbagliato in mappa: la chiave c:r passa dove "chat" no -> LEAK
        (("GET", "/v1/conversations"), "chat", "LEAK"),
        # endpoint senza scope dichiarato come scoped -> BROKEN
        (("GET", "/v1/user-memory/notes"), "chat", "BROKEN"),
    ],
)
def test_matrix_detects_drift(env, monkeypatch, op, scope, verdict):
    expected = dict(matrix.EXPECTED_SCOPE)
    if scope is None:
        expected.pop(op)
    else:
        expected[op] = scope
    monkeypatch.setattr(matrix, "EXPECTED_SCOPE", expected)
    finding = matrix.evaluate(env["send"], *op, env["keys"], "x" * 32)
    assert finding.verdict == verdict, finding


def test_in_handler_auth_endpoints_reject_keys(env):
    send = env["send"]
    key = env["keys"][matrix.ALL]
    for method, path, payload in matrix.IN_HANDLER_AUTH:
        for headers in ({"X-Api-Key": key}, {"Authorization": f"Bearer {key}"}):
            status, raw = send(
                method,
                path,
                {**headers, "Content-Type": "application/json"},
                matrix.json.dumps(payload).encode(),
            )
            assert status == 401, (method, path, raw)
