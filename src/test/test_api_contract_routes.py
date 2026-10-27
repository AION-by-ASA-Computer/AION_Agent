"""Le route di ``CONTRACT_ROUTES`` esistono, hanno un modello di risposta e lo
scope atteso da ``scripts/security/check_api_key_scopes.py``."""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from src.api.contract import CONTRACT_ROUTES, ContractRoute
from src.api.main import app

_SCOPES_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "security"
    / "check_api_key_scopes.py"
)


def _expected_scope() -> dict[tuple[str, str], str]:
    spec = importlib.util.spec_from_file_location(
        "check_api_key_scopes", _SCOPES_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    # Le dataclass dello script cercano il modulo in ``sys.modules``.
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module.EXPECTED_SCOPE


def _route(entry: ContractRoute) -> APIRoute:
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == entry.path
            and entry.method in route.methods
        ):
            return route
    raise AssertionError(f"{entry.method} {entry.path} non registrata")


@pytest.mark.parametrize("entry", CONTRACT_ROUTES, ids=lambda e: f"{e.method} {e.path}")
def test_contract_route_exists(entry: ContractRoute):
    route = _route(entry)
    if entry.kind == "json":
        assert route.response_model is not None, "manca response_model"
    else:
        assert route.response_class.media_type == "text/event-stream"
        assert "model" in route.responses.get(200, {}), "manca lo schema degli eventi"


def test_contract_scopes_match_expected():
    expected = _expected_scope()
    for entry in CONTRACT_ROUTES:
        assert expected.get((entry.method, entry.path)) == entry.scope, (
            f"{entry.method} {entry.path}"
        )


def test_contract_routes_documented():
    doc = (
        Path(__file__).resolve().parents[2] / "docs" / "api-and-runtime" / "rest-api.md"
    ).read_text(encoding="utf-8")
    for entry in CONTRACT_ROUTES:
        assert f"| `{entry.method}` | `{entry.path}` | `{entry.scope}` |" in doc, (
            f"{entry.method} {entry.path} manca dalla tabella del contratto"
        )
