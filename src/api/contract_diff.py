"""Snapshot OpenAPI del contratto e confronto tra due versioni.

``contract_openapi`` estrae dallo schema completo le route di
``CONTRACT_ROUTES`` e i ``components/schemas`` che usano. ``breaking_changes``
elenca le modifiche incompatibili per un client esistente:

- route o metodo rimossi;
- risposta: campo rimosso, campo non più obbligatorio, tipo allargato,
  variante di una union rimossa;
- richiesta: parametro o campo nuovo obbligatorio, opzionale diventato
  obbligatorio, valori di enum rimossi, body diventato obbligatorio.

Le aggiunte (route, campi di risposta, varianti, campi di richiesta opzionali)
sono compatibili. Una route marcata ``deprecated`` con ``x-sunset`` passato può
essere rimossa o cambiata (``src/api/deprecation.py``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.api.contract import CONTRACT_ROUTES

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "api-and-runtime"
    / "contract"
    / "openapi-contract.json"
)

_REF_PREFIX = "#/components/schemas/"


def _refs(node: Any, found: Set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            found.add(ref[len(_REF_PREFIX) :])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def contract_openapi(full: Dict[str, Any]) -> Dict[str, Any]:
    """Sottoinsieme di ``full`` con le sole route del contratto."""
    paths: Dict[str, Dict[str, Any]] = {}
    for route in CONTRACT_ROUTES:
        op = full["paths"][route.path][route.method.lower()]
        paths.setdefault(route.path, {})[route.method.lower()] = op

    all_schemas = full.get("components", {}).get("schemas", {})
    names: Set[str] = set()
    pending: Set[str] = set()
    _refs(paths, pending)
    while pending:
        name = pending.pop()
        if name in names:
            continue
        names.add(name)
        _refs(all_schemas.get(name, {}), pending)

    return {
        "openapi": full.get("openapi"),
        "info": {"title": full.get("info", {}).get("title"), "version": "contract"},
        "paths": paths,
        "components": {"schemas": {n: all_schemas[n] for n in sorted(names)}},
    }


class _Doc:
    def __init__(self, doc: Dict[str, Any]):
        self.schemas = doc.get("components", {}).get("schemas", {})

    def resolve(self, schema: Any) -> Dict[str, Any]:
        seen: Set[str] = set()
        while isinstance(schema, dict) and "$ref" in schema:
            name = schema["$ref"][len(_REF_PREFIX) :]
            if name in seen:
                break
            seen.add(name)
            schema = self.schemas.get(name, {})
        return schema if isinstance(schema, dict) else {}


def _variants(schema: Dict[str, Any]) -> Optional[List[Any]]:
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return schema[key]
    return None


def _types(doc: _Doc, schema: Any) -> Set[str]:
    """Tipi JSON ammessi da uno schema (``any`` se non vincolato)."""
    schema = doc.resolve(schema)
    variants = _variants(schema)
    if variants is not None:
        out: Set[str] = set()
        for v in variants:
            out |= _types(doc, v)
        return out
    t = schema.get("type")
    if isinstance(t, list):
        return set(t)
    if isinstance(t, str):
        return {t}
    if "properties" in schema:
        return {"object"}
    return {"any"}


def _variant_key(variant: Any) -> str:
    if isinstance(variant, dict) and "$ref" in variant:
        return variant["$ref"][len(_REF_PREFIX) :]
    if isinstance(variant, dict):
        if _variants(variant) is not None:
            # Union annidata (es. ChatStreamEvent): confrontata variante per variante.
            return "<union>"
        return str(variant.get("type") or variant.get("const") or variant)
    return str(variant)


def _response_diff(
    old_doc: _Doc,
    new_doc: _Doc,
    old: Any,
    new: Any,
    where: str,
    out: List[str],
    seen: Set[tuple],
) -> None:
    key = (
        old.get("$ref") if isinstance(old, dict) else None,
        new.get("$ref") if isinstance(new, dict) else None,
        where,
    )
    if key in seen:
        return
    seen.add(key)

    old_s, new_s = old_doc.resolve(old), new_doc.resolve(new)
    old_types, new_types = _types(old_doc, old_s), _types(new_doc, new_s)
    if "any" not in old_types and not new_types <= old_types:
        added = sorted(new_types - old_types)
        out.append(f"{where}: tipo allargato con {added}")
        return

    old_v, new_v = _variants(old_s), _variants(new_s)
    if old_v is not None and new_v is not None:
        new_by_key = {_variant_key(v): v for v in new_v}
        for v in old_v:
            k = _variant_key(v)
            if k not in new_by_key:
                out.append(f"{where}: variante {k} rimossa")
            else:
                _response_diff(
                    old_doc, new_doc, v, new_by_key[k], f"{where}<{k}>", out, seen
                )
        return

    old_props = old_s.get("properties") or {}
    new_props = new_s.get("properties") or {}
    old_req = set(old_s.get("required") or [])
    new_req = set(new_s.get("required") or [])
    for name, sub in old_props.items():
        if name not in new_props:
            out.append(f"{where}.{name}: campo rimosso")
            continue
        if name in old_req and name not in new_req:
            out.append(f"{where}.{name}: non più sempre presente")
        _response_diff(
            old_doc, new_doc, sub, new_props[name], f"{where}.{name}", out, seen
        )

    if "items" in old_s and "items" in new_s:
        _response_diff(
            old_doc, new_doc, old_s["items"], new_s["items"], f"{where}[]", out, seen
        )


def _request_diff(
    old_doc: _Doc, new_doc: _Doc, old: Any, new: Any, where: str, out: List[str]
) -> None:
    old_s, new_s = old_doc.resolve(old), new_doc.resolve(new)
    old_enum, new_enum = old_s.get("enum"), new_s.get("enum")
    if old_enum is not None and new_enum is not None:
        removed = [v for v in old_enum if v not in new_enum]
        if removed:
            out.append(f"{where}: valori enum rimossi {removed}")
    old_props = old_s.get("properties") or {}
    new_props = new_s.get("properties") or {}
    old_req = set(old_s.get("required") or [])
    for name in sorted(set(new_s.get("required") or []) - old_req):
        status = "nuovo campo" if name not in old_props else "campo"
        out.append(f"{where}.{name}: {status} obbligatorio")
    for name, sub in old_props.items():
        if name in new_props:
            _request_diff(
                old_doc, new_doc, sub, new_props[name], f"{where}.{name}", out
            )


def _json_schema(content: Dict[str, Any]) -> Any:
    for media in content.values():
        if isinstance(media, dict) and "schema" in media:
            return media["schema"]
    return None


def _sunset_passed(op: Dict[str, Any], today: date) -> bool:
    sunset = op.get("x-sunset")
    if not op.get("deprecated") or not isinstance(sunset, str):
        return False
    try:
        return date.fromisoformat(sunset) <= today
    except ValueError:
        return False


def breaking_changes(
    old: Dict[str, Any], new: Dict[str, Any], *, today: Optional[date] = None
) -> List[str]:
    """Modifiche di ``new`` incompatibili con i client scritti per ``old``."""
    today = today or date.today()
    old_doc, new_doc = _Doc(old), _Doc(new)
    out: List[str] = []
    for path, ops in old.get("paths", {}).items():
        for method, old_op in ops.items():
            where = f"{method.upper()} {path}"
            if _sunset_passed(old_op, today):
                continue
            new_op = new.get("paths", {}).get(path, {}).get(method)
            if new_op is None:
                out.append(f"{where}: route rimossa")
                continue

            old_params = {(p["in"], p["name"]): p for p in old_op.get("parameters", [])}
            for p in new_op.get("parameters", []):
                prev = old_params.get((p["in"], p["name"]))
                if p.get("required") and not (prev and prev.get("required")):
                    out.append(f"{where}: parametro {p['name']} obbligatorio")
                if prev is not None:
                    _request_diff(
                        old_doc,
                        new_doc,
                        prev.get("schema"),
                        p.get("schema"),
                        f"{where} {p['name']}",
                        out,
                    )

            old_body = old_op.get("requestBody") or {}
            new_body = new_op.get("requestBody") or {}
            if new_body.get("required") and not old_body.get("required"):
                out.append(f"{where}: body obbligatorio")
            old_schema = _json_schema(old_body.get("content", {}))
            new_schema = _json_schema(new_body.get("content", {}))
            if old_schema is not None and new_schema is not None:
                _request_diff(
                    old_doc, new_doc, old_schema, new_schema, f"{where} body", out
                )

            for status, old_resp in old_op.get("responses", {}).items():
                new_resp = new_op.get("responses", {}).get(status)
                if new_resp is None:
                    out.append(f"{where}: risposta {status} rimossa")
                    continue
                old_content = old_resp.get("content", {})
                new_content = new_resp.get("content", {})
                for media in old_content:
                    if media not in new_content:
                        out.append(f"{where} {status}: content type {media} rimosso")
                old_schema = _json_schema(old_content)
                new_schema = _json_schema(new_content)
                if old_schema is not None and new_schema is not None:
                    _response_diff(
                        old_doc,
                        new_doc,
                        old_schema,
                        new_schema,
                        f"{where} {status}",
                        out,
                        set(),
                    )
    return out
