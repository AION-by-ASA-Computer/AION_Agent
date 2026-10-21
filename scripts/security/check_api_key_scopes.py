#!/usr/bin/env python3
"""Verifica le API key per-utente su TUTTI gli endpoint del backend AION.

Lo script parla con il backend in esecuzione usando solo la stdlib e usa le
chiavi incollate in ``API_KEYS`` (sotto): niente login, niente creazione.

Preparazione (a mano, una volta):
  1. admin-ui -> Utenti: abilita le API key per l'utente (quota >= 6);
  2. chat-ui, loggato come quell'utente -> Impostazioni -> API key: crea 6
     chiavi, una per scope (chat, conversations:read, conversations:write,
     files:read, files:write) e una con tutti gli scope;
  3. incollale in ``API_KEYS``; opzionale: una chiave gia' revocata in
     ``REVOKED_KEY``.

Prove:
  Chiavi          ogni chiave ha esattamente gli scope della sua variabile e
                  tutte appartengono allo stesso utente (altrimenti exit 2).
  Trasporto       ``X-Api-Key``, ``Authorization: Bearer``, ``?access_token=``.
  Identita'       la chiave agisce come il proprietario: la conversazione creata
                  via chiave e' sua, header/body ``user_id`` ignorati.
  Matrice         ogni operazione dell'app (da ``/openapi.json`` o importando
                  ``src.api.main``) confrontata con ``EXPECTED_SCOPE``:
                  - endpoint con scope: la chiave con lo scope passa, le chiavi
                    senza ricevono ``403 missing_scope``;
                  - tutti gli altri: la chiave con tutti gli scope (via
                    ``X-Api-Key`` e via Bearer) riceve ``403 api_key_not_allowed``
                    o un altro 401/403; se passa anche senza credenziali
                    l'endpoint e' pubblico.
  Ciclo di vita   formato non valido, chiave sconosciuta, ``REVOKED_KEY``.
                  Scadenza e proprietario disabilitato sono coperti da
                  ``src/test/test_api_keys.py``.

Le richieste della matrice usano id casuali e body JSON ``[]``: l'auth viene
risolta prima della validazione del body, quindi un endpoint che accetta la
chiave risponde 404/422 senza effetti e nessuna prova avvia l'LLM. Un endpoint
che accettasse la chiave per errore pero' esegue: usare un'istanza di sviluppo.
L'unica scrittura voluta e' una conversazione di prova, cancellata subito.

Esiti:
  LEAK    la chiave entra dove non dovrebbe (scope mancante o endpoint senza scope)
  BROKEN  la chiave con lo scope giusto viene rifiutata
  FAIL    controllo di trasporto/identita'/ciclo di vita non rispettato
  OK      comportamento atteso
  PUBLIC  endpoint raggiungibile anche senza credenziali (informativo)
  SKIP    prova non applicabile (prerequisito mancante)
  ??      risposta inattesa: verificare a mano

Uso tipico:
  python scripts/security/check_api_key_scopes.py
  python scripts/security/check_api_key_scopes.py --detail
  python scripts/security/check_api_key_scopes.py --base-url https://host/api \\
      --only '^/v1/' --verbose

``--detail`` stampa, per ognuno dei 44 endpoint con scope, l'URL chiamato e una
riga per chiave: header inviato, esito atteso e risposta ottenuta.

Exit code 0 se nessun LEAK/BROKEN/FAIL, 1 altrimenti, 2 per errori di setup.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_HEADER = "X-AION-User-Id"
BODY_METHODS = ("POST", "PUT", "PATCH")

SCOPES = (
    "chat",
    "conversations:read",
    "conversations:write",
    "files:read",
    "files:write",
)
ALL = "all"
KEY_SCOPES: dict[str, tuple[str, ...]] = {**{s: (s,) for s in SCOPES}, ALL: SCOPES}

# Incolla qui le chiavi (``aion_...``) create da chat-ui -> Impostazioni ->
# API key, tutte dello stesso utente: una per scope e una con tutti gli scope.
API_KEYS: dict[str, str] = {
    "chat": "aion_cwlrq0pb_5q7ps5g3msbyhf56qpy0r4fbcauuqp6s",
    "conversations:read": "aion_gumkegrg_lk58q9yyb4bggd0vy6uxe1w4byl32ohn",
    "conversations:write": "aion_g0mry3kf_ay2zgqmkjv734cu106tn1vyqjwqr8fh1",
    "files:read": "aion_5b41duwd_mkz2ae2jw41h592im589gvsnsjh2ms2m",
    "files:write": "aion_f0544bt1_lug04rvdizoapo6q3a60uutpdjtqxlms",
    ALL: "aion_bb5qhpr5_fi5voo4m47bj7q9a28vdkdobb3ugxw9m",
}
# Opzionale: una chiave dello stesso utente gia' revocata da chat-ui.
REVOKED_KEY = ""

# Specifica (docs/security/api-keys.md): le uniche operazioni che accettano
# API key, con lo scope richiesto. Tutto il resto deve rifiutarle.
EXPECTED_SCOPE: dict[tuple[str, str], str] = {
    # chat
    ("POST", "/a2a/invoke"): "chat",
    ("POST", "/chat"): "chat",
    ("POST", "/chat/stop"): "chat",
    ("GET", "/profiles"): "chat",
    ("GET", "/sessions/{session_id}/charts"): "chat",
    ("POST", "/v1/chat"): "chat",
    ("POST", "/v1/chat/completions"): "chat",
    ("POST", "/v1/chat/prepare"): "chat",
    ("GET", "/v1/chat/prepare/status"): "chat",
    ("POST", "/v1/chat/stop"): "chat",
    ("POST", "/v1/chat/stream"): "chat",
    ("GET", "/v1/chat/stream/reconnect/{conversation_id}"): "chat",
    ("GET", "/v1/llm-providers"): "chat",
    ("GET", "/v1/models"): "chat",
    ("GET", "/v1/models/{model_id}"): "chat",
    # conversations:read
    ("GET", "/chat-ui/conversations"): "conversations:read",
    ("GET", "/chat-ui/conversations/{conv_id}"): "conversations:read",
    ("GET", "/chat-ui/conversations/{conv_id}/messages"): "conversations:read",
    ("GET", "/chat-ui/conversations/{conv_id}/stream-status"): "conversations:read",
    ("GET", "/chat-ui/conversations/{conv_id}/threads"): "conversations:read",
    ("GET", "/sessions/{session_id}/events/stream"): "conversations:read",
    ("GET", "/sessions/{session_id}/tool-ledger"): "conversations:read",
    ("GET", "/v1/conversations"): "conversations:read",
    ("GET", "/v1/conversations/{conversation_id}"): "conversations:read",
    ("GET", "/v1/conversations/{conversation_id}/messages"): "conversations:read",
    ("GET", "/v1/conversations/{conversation_id}/steps"): "conversations:read",
    # conversations:write
    ("POST", "/chat-ui/conversations"): "conversations:write",
    ("DELETE", "/chat-ui/conversations/{conv_id}"): "conversations:write",
    ("POST", "/chat-ui/conversations/{conv_id}/messages"): "conversations:write",
    (
        "DELETE",
        "/chat-ui/conversations/{conv_id}/messages/{message_id}",
    ): "conversations:write",
    (
        "POST",
        "/chat-ui/conversations/{conv_id}/messages/{message_id}/rate",
    ): "conversations:write",
    (
        "POST",
        "/chat-ui/conversations/{conv_id}/messages/{message_id}/steps",
    ): "conversations:write",
    (
        "PATCH",
        "/chat-ui/conversations/{conv_id}/messages/{message_id}/timeline",
    ): "conversations:write",
    ("PATCH", "/chat-ui/conversations/{conv_id}/metadata"): "conversations:write",
    ("POST", "/chat-ui/conversations/{conv_id}/threads"): "conversations:write",
    ("POST", "/v1/conversations"): "conversations:write",
    ("DELETE", "/v1/conversations/{conversation_id}"): "conversations:write",
    ("PATCH", "/v1/conversations/{conversation_id}"): "conversations:write",
    ("POST", "/v1/conversations/{conversation_id}/steps"): "conversations:write",
    # files
    ("GET", "/sessions/{session_id}/download"): "files:read",
    ("GET", "/sessions/{session_id}/files"): "files:read",
    ("GET", "/v1/conversations/{conversation_id}/files"): "files:read",
    ("POST", "/sessions/{session_id}/upload"): "files:write",
    ("POST", "/v1/conversations/{conversation_id}/files"): "files:write",
}

# Endpoint che verificano il chat token dentro l'handler: la matrice (body
# ``[]``) si ferma alla validazione, qui si prova con un body valido e innocuo.
IN_HANDLER_AUTH: tuple[tuple[str, str, dict], ...] = (
    ("PATCH", "/auth/me", {}),
    (
        "POST",
        "/auth/change-password",
        {"old_password": "not-the-password", "new_password": "never-applied"},
    ),
)

FAILING = ("LEAK", "BROKEN", "FAIL")
_SEVERITY = {"LEAK": 0, "BROKEN": 1, "??": 2, "PUBLIC": 3, "OK": 4}
_SHORT = {
    "chat": "chat",
    "conversations:read": "c:r",
    "conversations:write": "c:w",
    "files:read": "f:r",
    "files:write": "f:w",
    ALL: "all",
    "bearer": "all(bearer)",
    "anon": "anon",
}

# send(method, path, headers, body) -> (status, raw)
Sender = Callable[[str, str, dict, "bytes | None"], "tuple[int, bytes]"]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # I redirect (es. login SSO) puntano a host esterni: lo status basta.
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class Client:
    """Minimo wrapper HTTP senza credenziali proprie."""

    def __init__(self, base_url: str, timeout: float = 20):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        url = self.base + path
        req = urllib.request.Request(
            url, data=body, method=method, headers=dict(headers or {})
        )
        try:
            with _OPENER.open(req, timeout=self.timeout) as resp:
                # Uno stream SSE accettato non termina: basta lo status.
                if resp.headers.get_content_type() == "text/event-stream":
                    return resp.status, b""
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (TimeoutError, socket.timeout):
            return 0, b"<timeout>"
        except urllib.error.URLError as exc:
            _die(f"impossibile contattare {url}: {exc}")

    def send(self, method: str, path: str, headers: dict, body: bytes | None):
        return self.request(method, path, body=body, headers=headers)

    def get(self, path: str, headers: dict[str, str] | None = None):
        return self.request("GET", path, headers=headers)

    def send_json(self, method: str, path: str, payload, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        return self.request(method, path, body=json.dumps(payload).encode(), headers=h)


def _die(msg: str):
    print(f"ERRORE DI SETUP: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _snip(raw: bytes, n: int = 110) -> str:
    return raw.decode(errors="replace").replace("\n", " ")[:n]


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _json(raw: bytes):
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {}


def detail_code(raw: bytes) -> str:
    data = _json(raw)
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("code") or "")
    return ""


def _key_headers(key: str) -> dict[str, str]:
    return {"X-Api-Key": key}


# --------------------------------------------------------------------------
# Matrice endpoint x chiavi
# --------------------------------------------------------------------------


def normalize_template(path: str) -> str:
    """``/x/{p:path}`` -> ``/x/{p}`` (stessa forma di openapi.json)."""
    return re.sub(r"\{(\w+):[^}]+\}", r"{\1}", path)


def operations_from_openapi(doc: dict) -> list[tuple[str, str]]:
    ops = []
    for path, item in (doc.get("paths") or {}).items():
        for method in item:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                ops.append((method.upper(), normalize_template(path)))
    return sorted(set(ops), key=lambda o: (o[1], o[0]))


def operations_from_app(app) -> list[tuple[str, str]]:
    from fastapi.routing import APIRoute

    ops = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            ops.append((method, normalize_template(route.path)))
    return sorted(set(ops), key=lambda o: (o[1], o[0]))


def stale_expectations(ops: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Voci di ``EXPECTED_SCOPE`` che non corrispondono a nessuna operazione."""
    present = set(ops)
    return sorted(op for op in EXPECTED_SCOPE if op not in present)


@dataclass
class Outcome:
    status: int
    kind: str  # accepted | not_allowed | missing_scope | denied
    code: str
    body: str = ""

    def short(self) -> str:
        if self.kind == "accepted":
            return str(self.status) if self.status else "timeout"
        return f"{self.status}:{self.code or self.kind}"


@dataclass
class Finding:
    verdict: str
    method: str
    path: str
    scope: str | None
    detail: str
    outcomes: dict[str, Outcome] = field(default_factory=dict)
    url: str = ""


def classify(status: int, raw: bytes) -> Outcome:
    code, body = detail_code(raw), _snip(raw, 90)
    if status in (401, 403):
        if code == "api_key_not_allowed":
            return Outcome(status, "not_allowed", code, body)
        if code == "missing_scope":
            return Outcome(status, "missing_scope", code, body)
        return Outcome(status, "denied", code, body)
    # 2xx/3xx/404/422/5xx/timeout: l'autenticazione e' stata superata.
    return Outcome(status, "accepted", code, body)


def probe(
    send: Sender,
    method: str,
    path: str,
    key: str | None = None,
    *,
    bearer: bool = False,
) -> Outcome:
    headers: dict[str, str] = {}
    body = None
    if method in BODY_METHODS:
        # JSON valido ma mai un body accettabile: 422 dopo l'auth.
        body = b"[]"
        headers["Content-Type"] = "application/json"
    if key and bearer:
        headers["Authorization"] = f"Bearer {key}"
    elif key:
        headers.update(_key_headers(key))
    return classify(*send(method, path, headers, body))


def concrete_path(template: str, dummy: str) -> str:
    return re.sub(r"\{[^}]+\}", dummy, template)


def evaluate(
    send: Sender, method: str, template: str, keys: dict[str, str], dummy: str
) -> Finding:
    path = concrete_path(template, dummy)
    scope = EXPECTED_SCOPE.get((method, template))
    if scope is None:
        # Anche come Bearer: alcuni handler leggono solo ``Authorization``.
        outcomes = {
            ALL: probe(send, method, path, keys[ALL]),
            "bearer": probe(send, method, path, keys[ALL], bearer=True),
        }
        full = next(
            (o for o in outcomes.values() if o.kind == "accepted"), outcomes[ALL]
        )
        if full.kind == "accepted":
            anon = probe(send, method, path)
            outcomes["anon"] = anon
            if anon.kind == "accepted":
                return Finding("PUBLIC", method, template, None, "", outcomes)
            return Finding(
                "LEAK",
                method,
                template,
                None,
                f"chiave accettata ({full.short()}), senza credenziali {anon.short()}",
                outcomes,
            )
        if full.kind == "missing_scope":
            return Finding(
                "??",
                method,
                template,
                None,
                "chiede uno scope fuori da SCOPES",
                outcomes,
            )
        return Finding("OK", method, template, None, full.short(), outcomes)

    outcomes: dict[str, Outcome] = {}
    problems: list[tuple[str, str]] = []
    for label, granted in KEY_SCOPES.items():
        out = probe(send, method, path, keys[label])
        outcomes[label] = out
        if scope in granted:
            if out.kind != "accepted":
                problems.append(("BROKEN", f"{_SHORT[label]} rifiutata {out.short()}"))
        elif out.kind == "accepted":
            problems.append(("LEAK", f"{_SHORT[label]} accettata {out.short()}"))
        elif out.kind != "missing_scope":
            problems.append(("??", f"{_SHORT[label]} {out.short()}"))
    verdict = min((v for v, _ in problems), key=_SEVERITY.get, default="OK")
    summary = " ".join(f"{_SHORT[k]}={o.short()}" for k, o in outcomes.items())
    detail = "; ".join(d for _, d in problems) or summary
    return Finding(verdict, method, template, scope, detail, outcomes, path)


def run_matrix(
    send: Sender,
    ops: Iterable[tuple[str, str]],
    keys: dict[str, str],
    *,
    on_result: Callable[[Finding], None] | None = None,
) -> list[Finding]:
    dummy = uuid.uuid4().hex
    findings = []
    for method, template in ops:
        f = evaluate(send, method, template, keys, dummy)
        findings.append(f)
        if on_result:
            on_result(f)
    return findings


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


class Report:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.counts: dict[str, int] = {}
        self.failures: list[str] = []

    def section(self, title: str) -> None:
        print(f"\n== {title}")

    def line(self, verdict: str, name: str, detail: str = "", status=None) -> None:
        self.counts[verdict] = self.counts.get(verdict, 0) + 1
        if verdict in FAILING:
            self.failures.append(f"{verdict} {name}")
        st = f"  (HTTP {status})" if status is not None else ""
        print(f"  [{verdict:<6}] {name}{st}  {detail}".rstrip())

    def expect(
        self,
        name: str,
        status: int,
        raw: bytes,
        *,
        want_status: int | tuple[int, ...],
        want_code: str | tuple[str, ...] | None = None,
    ) -> bool:
        statuses = want_status if isinstance(want_status, tuple) else (want_status,)
        codes = (want_code,) if isinstance(want_code, str) else want_code
        code = detail_code(raw)
        ok = status in statuses and (codes is None or code in codes)
        detail = code or _snip(raw, 80)
        if not ok:
            want = "/".join(map(str, statuses)) + (
                f" {'|'.join(codes)}" if codes else ""
            )
            detail = f"atteso {want}, ottenuto: {detail}"
        self.line("OK" if ok else "FAIL", name, detail, status)
        return ok

    def finding(self, f: Finding) -> None:
        self.counts[f.verdict] = self.counts.get(f.verdict, 0) + 1
        if f.verdict in FAILING:
            self.failures.append(f"{f.verdict} {f.method} {f.path}")
        if f.verdict in ("OK", "PUBLIC") and not self.verbose:
            return
        scope = f"[{f.scope}]" if f.scope else ""
        print(f"  [{f.verdict:<6}] {f.method:<6} {f.path} {scope}  {f.detail}")

    def scoped_detail(self, f: Finding, base_url: str, keys: dict[str, str]) -> None:
        """Una riga per chiave: header inviato, risposta, atteso, esito."""
        body = "  body: []" if f.method in BODY_METHODS else ""
        print(f"\n  [{f.verdict:<6}] {f.method} {f.path}  scope={f.scope}")
        print(f"           {f.method} {base_url}{f.url}{body}")
        for label, out in f.outcomes.items():
            if f.scope in KEY_SCOPES[label]:
                want, ok = "passa (non 401/403)", out.kind == "accepted"
                bad = "BROKEN"
            else:
                want, ok = "403 missing_scope", out.kind == "missing_scope"
                bad = "LEAK" if out.kind == "accepted" else "??"
            got = f"{out.status} {out.code}" if out.code else out.short()
            if out.kind == "accepted" and out.body:
                got += f"  {out.body}"
            print(
                f"           {'ok' if ok else bad:<6} X-Api-Key {label:<20}"
                f" {keys[label][:14]}…  atteso {want:<20} -> {got}"
            )


# --------------------------------------------------------------------------
# Scenario
# --------------------------------------------------------------------------


def _load_operations(client: Client, source: str) -> list[tuple[str, str]]:
    if source == "openapi":
        status, raw = client.get("/openapi.json")
        if status == 200:
            return operations_from_openapi(_json(raw))
        print(f"  /openapi.json -> {status}: uso le route del checkout locale")
    sys.path.insert(0, str(REPO_ROOT))
    from src.api.main import app  # noqa: E402

    return operations_from_app(app)


# Un endpoint innocuo per scope: verifica che ogni chiave abbia gli scope della
# sua variabile prima della matrice (una chiave scambiata non e' un bug).
_SCOPE_PROBES: dict[str, tuple[str, str]] = {
    "chat": ("GET", "/profiles"),
    "conversations:read": ("GET", "/v1/conversations"),
    "conversations:write": ("DELETE", "/v1/conversations/{id}"),
    "files:read": ("GET", "/sessions/{id}/files"),
    "files:write": ("POST", "/sessions/{id}/upload"),
}


def _check_keys(rep: Report, client: Client, keys: dict[str, str]) -> None:
    rep.section("Chiavi configurate (API_KEYS)")
    empty = [label for label in KEY_SCOPES if not keys.get(label)]
    if empty:
        _die(f"API_KEYS senza valore per: {', '.join(empty)}")
    dummy = uuid.uuid4().hex
    for label, granted in KEY_SCOPES.items():
        status, raw = client.get("/profiles", headers=_key_headers(keys[label]))
        if status == 401:
            _die(f"API_KEYS[{label!r}] rifiutata: {detail_code(raw) or _snip(raw)}")
        wrong = []
        for scope, (method, template) in _SCOPE_PROBES.items():
            out = probe(
                client.send, method, concrete_path(template, dummy), keys[label]
            )
            if (out.kind == "accepted") != (scope in granted):
                wrong.append(f"{scope}={out.short()}")
        if wrong:
            _die(
                f"API_KEYS[{label!r}] non ha gli scope {list(granted)}: "
                + ", ".join(wrong)
            )
        print(f"  {label:<20} {keys[label][:13]}...  scope OK")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="http://localhost:8001")
    ap.add_argument(
        "--profile",
        default="generic_assistant",
        help="profilo per la conversazione di prova (identita')",
    )
    ap.add_argument(
        "--routes-from",
        choices=("openapi", "repo"),
        default="openapi",
        help="elenco operazioni: openapi.json del backend o import di src.api.main",
    )
    ap.add_argument("--only", help="regex sul path: limita la matrice")
    ap.add_argument("--timeout", type=float, default=20)
    ap.add_argument(
        "--verbose", action="store_true", help="stampa anche gli esiti OK/PUBLIC"
    )
    ap.add_argument(
        "--detail",
        action="store_true",
        help="per ogni endpoint con scope: URL, chiave usata e risposta",
    )
    args = ap.parse_args()

    rep = Report(args.verbose)
    client = Client(args.base_url, args.timeout)
    keys = {label: API_KEYS.get(label, "").strip() for label in KEY_SCOPES}

    print(f"Backend: {args.base_url}")
    _check_keys(rep, client, keys)
    _check_transport(rep, client, keys)
    _check_identity(rep, client, keys, args.profile)
    _check_matrix(rep, client, keys, args)
    _check_lifecycle(rep, client, keys)

    rep.section("Riepilogo")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(rep.counts.items())))
    for line in rep.failures:
        print(f"  {line}")
    return 1 if rep.failures else 0


def _check_transport(rep: Report, client: Client, keys: dict[str, str]) -> None:
    rep.section("Trasporto della chiave")
    chat, read = keys["chat"], keys["conversations:read"]
    for name, path, headers in (
        ("X-Api-Key", "/profiles", {"X-Api-Key": chat}),
        ("Authorization: Bearer", "/profiles", {"Authorization": f"Bearer {chat}"}),
        ("?access_token=", f"/profiles?access_token={_q(chat)}", {}),
    ):
        status, raw = client.get(path, headers=headers)
        rep.expect(f"{name} con scope chat su /profiles", status, raw, want_status=200)
    status, raw = client.get("/profiles", headers={"Authorization": f"Bearer {read}"})
    rep.expect(
        "Bearer senza scope chat",
        status,
        raw,
        want_status=403,
        want_code="missing_scope",
    )
    status, raw = client.get(f"/v1/me/api-keys?access_token={_q(keys[ALL])}")
    rep.expect(
        "?access_token= su endpoint senza scope",
        status,
        raw,
        want_status=403,
        want_code="api_key_not_allowed",
    )


def _check_identity(
    rep: Report, client: Client, keys: dict[str, str], profile: str
) -> None:
    rep.section("Identita': la chiave agisce come il proprietario")
    intruder = "intruso-" + uuid.uuid4().hex[:8]
    status, raw = client.send_json(
        "POST",
        "/v1/conversations",
        {"profile": profile, "title": "api-key scope test", "user_id": intruder},
        headers={**_key_headers(keys[ALL]), USER_HEADER: intruder},
    )
    conv = _json(raw)
    if status == 403 and detail_code(raw) == "profile_not_allowed":
        rep.line(
            "SKIP",
            "identita'",
            f"profilo {profile!r} non consentito: usa --profile",
            status,
        )
        return
    if status not in (200, 201) or not conv.get("id"):
        rep.line("??", "creazione conversazione via chiave", _snip(raw, 120), status)
        return
    cid, owner = conv["id"], conv.get("user_id")
    rep.line(
        "OK" if owner and owner != intruder else "FAIL",
        "owner = proprietario (header/body user_id ignorati)",
        f"user_id={owner!r}",
        status,
    )
    # Ownership: un'altra chiave la legge solo se ha lo stesso proprietario.
    read = _key_headers(keys["conversations:read"])
    status, raw = client.get(f"/v1/conversations/{cid}", headers=read)
    if status == 404:
        _die("le chiavi in API_KEYS appartengono a utenti diversi")
    rep.expect(
        "letta da un'altra chiave dello stesso utente", status, raw, want_status=200
    )
    status, raw = client.get(f"/chat-ui/conversations/{cid}", headers=read)
    rep.expect(
        "visibile anche da /chat-ui (sidebar dell'utente)", status, raw, want_status=200
    )
    status, raw = client.get(
        f"/v1/conversations?user_id={_q(intruder)}", headers=_key_headers(keys[ALL])
    )
    owners = {c.get("user_id") for c in _json(raw).get("data") or []}
    rep.line(
        "OK" if status == 200 and owners <= {owner} else "FAIL",
        "lista ?user_id=altro: solo conversazioni del proprietario",
        f"owner visti: {sorted(o for o in owners if o)}",
        status,
    )
    status, raw = client.request(
        "DELETE",
        f"/v1/conversations/{cid}",
        headers=_key_headers(keys["conversations:write"]),
    )
    print(f"  conversazione di test cancellata: HTTP {status}")


def _check_matrix(rep: Report, client: Client, keys: dict[str, str], args) -> None:
    rep.section("Matrice endpoint x scope")
    ops = _load_operations(client, args.routes_from)
    for op in stale_expectations(ops):
        rep.line("??", f"{op[0]} {op[1]}", "in EXPECTED_SCOPE ma assente dall'app")
    if args.only:
        rx = re.compile(args.only)
        ops = [op for op in ops if rx.search(op[1])]
    scoped = sum(1 for op in ops if op in EXPECTED_SCOPE)
    print(f"  {len(ops)} operazioni ({scoped} con scope, {len(ops) - scoped} senza)")
    findings = run_matrix(client.send, ops, keys, on_result=rep.finding)
    public = [
        f"{f.method} {f.path} ({f.outcomes['anon'].short()})"
        for f in findings
        if f.verdict == "PUBLIC"
    ]
    if public and not args.verbose:
        print(f"  PUBLIC (senza credenziali, {len(public)}): " + ", ".join(public))
    if args.detail:
        rep.section("Dettaglio endpoint con scope (una richiesta per chiave)")
        for f in findings:
            if f.scope:
                rep.scoped_detail(f, client.base, keys)

    # Auth fatta nell'handler dopo la validazione del body: con ``[]`` la
    # matrice vede 422 (PUBLIC). Con un body valido la chiave va rifiutata.
    rep.section("Endpoint con auth nell'handler (body valido)")
    for method, path, payload in IN_HANDLER_AUTH:
        for bearer in (False, True):
            hdrs = (
                {"Authorization": f"Bearer {keys[ALL]}"}
                if bearer
                else _key_headers(keys[ALL])
            )
            status, raw = client.send_json(method, path, payload, headers=hdrs)
            rep.expect(
                f"{method} {path} {'Bearer' if bearer else 'X-Api-Key'}",
                status,
                raw,
                want_status=(401, 403),
            )


def _check_lifecycle(rep: Report, client: Client, keys: dict[str, str]) -> None:
    rep.section("Ciclo di vita / validazione")
    checks = [
        ("formato non valido", "aion_nope", "api_key_invalid_format"),
        (
            "chiave sconosciuta",
            f"aion_{secrets.token_hex(4)}_{secrets.token_hex(16)}",
            "api_key_invalid",
        ),
    ]
    if REVOKED_KEY.strip():
        checks.append(("REVOKED_KEY", REVOKED_KEY.strip(), "api_key_revoked"))
    else:
        rep.line("SKIP", "chiave revocata", "REVOKED_KEY vuota")
    for name, key, code in checks:
        status, raw = client.get("/profiles", headers=_key_headers(key))
        rep.expect(name, status, raw, want_status=401, want_code=code)


if __name__ == "__main__":
    sys.exit(main())
