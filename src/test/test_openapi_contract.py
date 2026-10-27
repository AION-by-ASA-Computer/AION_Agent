"""Lo schema OpenAPI delle route del contratto coincide con lo snapshot committato.

- Una modifica incompatibile (``src/api/contract_diff.py``) fa fallire il test:
  serve prima la deprecazione con ``Sunset`` (``docs/api-and-runtime/rest-api.md``).
- Una modifica solo additiva fa fallire il test finché lo snapshot non viene
  rigenerato con ``python scripts/export_openapi.py --update``, così il
  cambiamento compare nel diff del commit.
"""

import copy
import json
from datetime import date

from src.api.contract_diff import SNAPSHOT_PATH, breaking_changes, contract_openapi
from src.api.main import app

UPDATE_HINT = "eseguire `python scripts/export_openapi.py --update`"


def _current():
    return json.loads(json.dumps(contract_openapi(app.openapi()), sort_keys=True))


def test_contract_has_no_breaking_changes():
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    problems = breaking_changes(snapshot, _current())
    assert not problems, "modifiche incompatibili al contratto API:\n" + "\n".join(
        problems
    )


def test_contract_snapshot_up_to_date():
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert _current() == snapshot, f"snapshot OpenAPI non aggiornato: {UPDATE_HINT}"


# --- breaking_changes su schemi minimi ----------------------------------------


def _doc(props, required=("id",), extra_paths=None, **op):
    paths = {
        "/x": {
            "get": {
                "parameters": op.pop("parameters", []),
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Out"}
                            }
                        }
                    }
                },
                **op,
            }
        }
    }
    paths.update(extra_paths or {})
    return {
        "paths": paths,
        "components": {
            "schemas": {
                "Out": {
                    "type": "object",
                    "properties": props,
                    "required": list(required),
                }
            }
        },
    }


BASE_PROPS = {"id": {"type": "string"}, "n": {"type": "integer"}}


def test_identical_and_additive_are_compatible():
    old = _doc(dict(BASE_PROPS))
    assert breaking_changes(old, copy.deepcopy(old)) == []
    new = _doc({**BASE_PROPS, "extra": {"type": "string"}})
    new["paths"]["/y"] = {"get": {"responses": {}}}
    assert breaking_changes(old, new) == []


def test_removed_route_and_field():
    old = _doc(dict(BASE_PROPS))
    assert breaking_changes(old, {"paths": {}, "components": {}}) == [
        "GET /x: route rimossa"
    ]
    new = _doc({"id": {"type": "string"}})
    assert breaking_changes(old, new) == ["GET /x 200.n: campo rimosso"]


def test_type_change_and_no_longer_required():
    old = _doc(dict(BASE_PROPS))
    new = _doc({**BASE_PROPS, "n": {"type": "string"}})
    assert breaking_changes(old, new) == ["GET /x 200.n: tipo allargato con ['string']"]
    new = _doc(dict(BASE_PROPS), required=())
    assert breaking_changes(old, new) == ["GET /x 200.id: non più sempre presente"]


def test_new_required_parameter_and_enum_narrowed():
    param = {"in": "query", "name": "mode", "schema": {"enum": ["a", "b"]}}
    old = _doc(dict(BASE_PROPS), parameters=[param])
    new = _doc(
        dict(BASE_PROPS),
        parameters=[
            {**param, "schema": {"enum": ["a"]}},
            {"in": "query", "name": "q", "required": True, "schema": {}},
        ],
    )
    assert breaking_changes(old, new) == [
        "GET /x mode: valori enum rimossi ['b']",
        "GET /x: parametro q obbligatorio",
    ]


def test_expired_sunset_allows_removal():
    old = _doc(dict(BASE_PROPS), deprecated=True, **{"x-sunset": "2026-01-01"})
    gone = {"paths": {}, "components": {}}
    assert breaking_changes(old, gone, today=date(2026, 1, 2)) == []
    assert breaking_changes(old, gone, today=date(2025, 12, 31)) == [
        "GET /x: route rimossa"
    ]
