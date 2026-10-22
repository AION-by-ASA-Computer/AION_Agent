#!/usr/bin/env python3
"""Attacco simulato: un utente autenticato prova a leggere/scrivere le chat altrui.

Lo script parla con il backend AION in esecuzione usando solo la stdlib e
copre le falle di identita'/ownership individuate fuori da ``/admin``:

  F1  /chat-ui/*: utente preso da ``X-AION-User-Id`` invece che dal token.
  F2  ``NEXT_PUBLIC_AION_CHAT_UI_SECRET`` nel bundle browser + il secret
      interno restituisce ``roles=["admin"]``.
  F3  ownership mancante: /sessions/* (files, download, tool-ledger,
      events/stream, upload, charts), /debug/*, /a2a/invoke senza auth,
      /cron-jobs con session_id altrui, /v1/conversations/{id}/steps|files,
      /v1/chat (sync + reconnect), /v1/chat/completions, POST /chat legacy.
  F4  ``_resolve_chat_user_id`` / ``resolve_research_owner`` si fidano di
      header/body per identita' diverse dal token chat.
  F5  /admin/ltm/*, /admin/memory/facts, /admin/diagnostics/file.

Scenario (default: vittima ``eventsplusit@gmail.com``, attaccante ``bob``):
  1. login dei due utenti di test;
  2. la vittima crea una conversazione con titolo, messaggio e file che
     contengono un marker segreto;
  3. l'attaccante prova ad accedervi con il proprio token, falsificando
     ``X-AION-User-Id`` e, se il secret risulta pubblico, usando il secret
     interno del BFF come farebbe un browser qualsiasi.

Esiti:
  VULN  dati della vittima letti/scritti (o privilegio ottenuto): falla aperta
  OK    accesso negato (401/403/404) o marker non visibile
  SKIP  prova non applicabile (feature spenta, prerequisito mancante)
  ??    risposta inattesa: verificare a mano

Le prove che fanno girare l'LLM (/v1/chat, /chat, completions, a2a con
sessione della vittima, reconnect SSE) sono opzionali: ``--with-llm``.

Uso tipico:
  python scripts/security/check_conversation_isolation.py
  python scripts/security/check_conversation_isolation.py --with-llm \\
      --chat-ui-url http://localhost:8003

Exit code 0 se nessuna VULN, 1 se almeno una VULN, 2 per errori di setup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SECRET_HEADER = "X-AION-Chat-Ui-Secret"
USER_HEADER = "X-AION-User-Id"
DENIED = (401, 403, 404)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Client:
    """Minimo wrapper HTTP attorno a un utente (token opzionale)."""

    def __init__(self, base_url: str, label: str):
        self.base = base_url.rstrip("/")
        self.label = label
        self.token: str | None = None
        self.user_id: str | None = None
        self.roles: list[str] = []

    def _headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        hdrs = dict(headers or {})
        if self.token and "Authorization" not in hdrs:
            hdrs["Authorization"] = f"Bearer {self.token}"
        # None = "togli questo header" (es. richiesta senza credenziali)
        return {k: v for k, v in hdrs.items() if v is not None}

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> tuple[int, bytes]:
        url = self.base + path
        req = urllib.request.Request(
            url, data=body, method=method, headers=self._headers(headers)
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (TimeoutError, socket.timeout):
            return 0, b"<timeout>"
        except urllib.error.URLError as exc:
            raise SystemExit(f"[{self.label}] impossibile contattare {url}: {exc}")

    def stream(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        max_seconds: float = 4.0,
    ) -> tuple[int, bytes]:
        """Legge una risposta SSE per al massimo ``max_seconds``."""
        url = self.base + path
        req = urllib.request.Request(
            url, data=body, method=method, headers=self._headers(headers)
        )
        chunks: list[bytes] = []
        deadline = time.monotonic() + max_seconds
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, max_seconds)) as resp:
                status = resp.status
                while time.monotonic() < deadline:
                    try:
                        line = resp.readline()
                    except (TimeoutError, socket.timeout):
                        break
                    if not line:
                        break
                    chunks.append(line)
                return status, b"".join(chunks)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (TimeoutError, socket.timeout):
            return 0, b"".join(chunks) or b"<timeout>"
        except urllib.error.URLError as exc:
            raise SystemExit(f"[{self.label}] impossibile contattare {url}: {exc}")

    def get(self, path: str, headers: dict[str, str] | None = None, **kw):
        return self.request("GET", path, headers=headers, **kw)

    def send_json(
        self,
        method: str,
        path: str,
        payload,
        headers: dict[str, str] | None = None,
        **kw,
    ):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self.request(
            method, path, body=json.dumps(payload).encode(), headers=h, **kw
        )

    def login(self, username: str, password: str) -> None:
        status, raw = self.send_json(
            "POST", "/auth/login", {"username": username, "password": password}
        )
        if status != 200:
            raise SystemExit(
                f"[{self.label}] login fallito ({status}): {_snip(raw, 300)}"
            )
        data = json.loads(raw or b"{}")
        if "access_token" not in data:
            raise SystemExit(
                f"[{self.label}] login senza token (MFA/SSO attivo?): {_snip(raw, 300)}"
            )
        self.token = data["access_token"]
        self.user_id = data.get("user_id") or username
        self.roles = list(data.get("roles") or [])

    def preflight(self) -> None:
        """Il token deve passare i gate SSO/2FA, altrimenti ogni prova e' un 403
        che non dice nulla sull'ownership (falso OK)."""
        status, raw = self.get(f"/sessions/{uuid.uuid4().hex}/files")
        if status == 403 and (
            b"sso_link_required" in raw or b"mfa_enrollment_required" in raw
        ):
            raise SystemExit(
                f"[{self.label}] token bloccato dai gate ({_snip(raw, 120)}). "
                "Le prove non sarebbero significative: riporta login_mode a "
                "'password' o avvia il backend con AION_SSO_FORCE_PASSWORD=1."
            )
        if status == 401:
            raise SystemExit(f"[{self.label}] token rifiutato: {_snip(raw, 200)}")


def _snip(raw: bytes, n: int = 110) -> str:
    return raw.decode(errors="replace").replace("\n", " ")[:n]


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _multipart(filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----aion-isolation-" + uuid.uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            (
                'Content-Disposition: form-data; name="files"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            b"Content-Type: text/plain\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------
# Secret interno del BFF chat-ui
# --------------------------------------------------------------------------


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip().removeprefix("export ").strip()] = val.strip().strip("'\"")
    return out


def _known_internal_secret(cli_value: str | None, repo_root: Path) -> str | None:
    """Valore del secret, come lo conosce il BFF legittimo (non l'attaccante)."""
    if cli_value:
        return cli_value
    for key in ("AION_CHAT_UI_INTERNAL_SECRET", "NEXT_PUBLIC_AION_CHAT_UI_SECRET"):
        if os.getenv(key):
            return os.environ[key].strip()
    for env_path in (
        repo_root / ".env",
        repo_root / "chat-ui" / ".env.local",
        repo_root / "chat-ui" / ".env",
    ):
        env = _read_env_file(env_path)
        for key in ("AION_CHAT_UI_INTERNAL_SECRET", "NEXT_PUBLIC_AION_CHAT_UI_SECRET"):
            if env.get(key):
                return env[key]
    return None


def _client_code_reads_public_secret(repo_root: Path) -> list[str]:
    """File del client Next.js che leggono la variabile NEXT_PUBLIC_ del secret."""
    hits: list[str] = []
    chat_ui = repo_root / "chat-ui"
    for sub in ("lib", "app", "components", "hooks"):
        root = chat_ui / sub
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if f.suffix not in (".ts", ".tsx", ".js", ".jsx") or not f.is_file():
                continue
            try:
                if "NEXT_PUBLIC_AION_CHAT_UI_SECRET" in f.read_text(encoding="utf-8"):
                    hits.append(str(f.relative_to(repo_root)))
            except (OSError, UnicodeDecodeError):
                continue
    return hits


def _bundle_contains(
    chat_ui_url: str, secret: str, max_files: int = 400
) -> bool | None:
    """Scarica le pagine chat-ui e i loro JS pubblici; True se c'e' il secret.

    None se chat-ui non e' raggiungibile.
    """
    base = chat_ui_url.rstrip("/")
    seen: set[str] = set()
    queue: list[str] = []
    reached = False
    script_re = re.compile(r"""["'(](/?_next/static/[^"'()\s]+?\.js)""")
    for page in ("/", "/login", "/c/new"):
        try:
            with urllib.request.urlopen(base + page, timeout=15) as resp:
                html = resp.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            continue
        reached = True
        if secret in html:
            return True
        queue.extend(m.group(1) for m in script_re.finditer(html))
    if not reached:
        return None
    while queue and len(seen) < max_files:
        rel = "/" + queue.pop(0).lstrip("/")
        if rel in seen:
            continue
        seen.add(rel)
        try:
            with urllib.request.urlopen(base + rel, timeout=15) as resp:
                js = resp.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            continue
        if secret in js:
            return True
        queue.extend(m.group(1) for m in script_re.finditer(js))
    return False


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


class Report:
    def __init__(self, marker: str):
        self.marker = marker
        self.vulns: list[str] = []
        self.unclear: list[str] = []

    def section(self, title: str) -> None:
        print(f"\n== {title}")

    def _line(self, verdict: str, name: str, status: int | None, detail: str) -> None:
        st = f"HTTP {status}" if status is not None else "-"
        print(f"  [{verdict:<4}] {name}  ({st})  {detail}")
        if verdict == "VULN":
            self.vulns.append(name)
        elif verdict == "??":
            self.unclear.append(name)

    def leak(self, name: str, status: int, raw: bytes) -> None:
        """VULN se il marker della vittima compare nella risposta."""
        if self.marker.encode() in raw:
            self._line("VULN", name, status, "marker della vittima nella risposta")
        elif status in DENIED or 200 <= status < 300:
            self._line("OK", name, status, _snip(raw, 80))
        else:
            self._line("??", name, status, _snip(raw, 80))

    def access(self, name: str, status: int, raw: bytes, note: str = "") -> None:
        """VULN se la richiesta e' andata a buon fine (2xx)."""
        if self.marker.encode() in raw or 200 <= status < 300:
            self._line("VULN", name, status, note or "accesso consentito")
        elif status in DENIED:
            self._line("OK", name, status, _snip(raw, 80))
        elif status == 503:
            self._line("SKIP", name, status, _snip(raw, 80))
        else:
            self._line("??", name, status, _snip(raw, 80))

    def flag(self, verdict: str, name: str, detail: str, status: int | None = None):
        self._line(verdict, name, status, detail)


# --------------------------------------------------------------------------
# Scenario
# --------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--base-url", default="http://localhost:8001")
    ap.add_argument("--victim-user", default="eventsplusit@gmail.com")
    ap.add_argument("--victim-pass", default="events")
    ap.add_argument("--other-user", default="bob")
    ap.add_argument("--other-pass", default="bob")
    ap.add_argument("--profile", default="generic_assistant")
    ap.add_argument(
        "--stream-profile",
        default="document_extractor",
        help="profilo senza QueryMemory per il turno SSE della prova reconnect",
    )
    ap.add_argument(
        "--chat-ui-url",
        default="http://localhost:8003",
        help="chat-ui da cui scaricare il bundle JS per cercare il secret",
    )
    ap.add_argument(
        "--chat-ui-secret",
        help="valore di AION_CHAT_UI_INTERNAL_SECRET (default: env / .env del repo)",
    )
    ap.add_argument(
        "--assume-secret-leaked",
        action="store_true",
        help="fai usare il secret all'attaccante anche se non e' nel bundle",
    )
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="checkout del codice in esecuzione (controllo statico chat-ui e .env)",
    )
    ap.add_argument(
        "--other-api-key",
        help="API key (aion_...) dell'attaccante per le prove /v1/conversations/*",
    )
    ap.add_argument(
        "--with-llm",
        action="store_true",
        help="esegue anche le prove che avviano un turno LLM",
    )
    ap.add_argument(
        "--keep",
        action="store_true",
        help="non cancellare la conversazione della vittima a fine test",
    )
    args = ap.parse_args()

    marker = "AIONSECRET" + uuid.uuid4().hex
    rep = Report(marker)
    victim = Client(args.base_url, "vittima")
    other = Client(args.base_url, "attaccante")
    anon = Client(args.base_url, "anonimo")

    print(f"Backend: {args.base_url}")
    print(f"Marker segreto: {marker}")

    victim.login(args.victim_user, args.victim_pass)
    other.login(args.other_user, args.other_pass)
    if victim.user_id == other.user_id:
        raise SystemExit(
            "I due account risolvono allo stesso user_id: usa account distinti."
        )
    victim.preflight()
    other.preflight()
    print(
        f"Login OK — vittima={victim.user_id!r} roles={victim.roles}  "
        f"attaccante={other.user_id!r} roles={other.roles}"
    )

    secret = _known_internal_secret(args.chat_ui_secret, args.repo_root)
    # La vittima si comporta come il client chat-ui reale: token + header utente
    # (+ secret interno, che su main e' richiesto da /chat-ui/*).
    vh = {USER_HEADER: victim.user_id}
    if secret:
        vh[SECRET_HEADER] = secret

    # ---------------------------------------------------------------- setup
    rep.section("Setup: la vittima crea e popola la conversazione")
    status, raw = victim.send_json(
        "POST",
        "/chat-ui/conversations",
        {"profile": args.profile, "title": f"chat riservata {marker}"},
        headers=vh,
    )
    if status not in (200, 201):
        hint = "" if secret else " (manca il secret interno: passa --chat-ui-secret)"
        raise SystemExit(
            f"creazione conversazione fallita ({status}){hint}: {_snip(raw, 300)}"
        )
    conv_id = json.loads(raw)["id"]
    print(f"  conversazione vittima: {conv_id}")

    status, raw = victim.send_json(
        "POST",
        f"/chat-ui/conversations/{conv_id}/messages",
        {"role": "assistant", "content": f"appunto privato: {marker}"},
        headers=vh,
    )
    print(f"  messaggio con marker: HTTP {status}")

    upload_name = f"secret_{marker}.txt"
    body, ctype = _multipart(upload_name, f"documento riservato - {marker}\n".encode())
    status, raw = victim.request(
        "POST",
        f"/sessions/{conv_id}/upload",
        body=body,
        headers={**vh, "Content-Type": ctype},
    )
    rel_path = f"uploads/{upload_name}"
    try:
        rel_path = json.loads(raw)["files"][0].get("relative_path") or rel_path
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    print(f"  file con marker: HTTP {status}  ({rel_path})")

    s_own, raw_own = victim.get(
        f"/chat-ui/conversations/{conv_id}/messages", headers=vh
    )
    s_dl, raw_dl = victim.get(
        f"/sessions/{conv_id}/download?relative_path={_q(rel_path)}", headers=vh
    )
    if not (s_own == 200 and marker.encode() in raw_own):
        raise SystemExit(
            "SETUP NON VALIDO: la vittima non rilegge il proprio marker "
            f"(HTTP {s_own}). Controlla profili/DB prima di fidarti dell'esito."
        )
    file_ok = s_dl == 200 and marker.encode() in raw_dl
    print(
        "  sanity: messaggi OK, file "
        + (
            "OK"
            if file_ok
            else f"NON rileggibile (HTTP {s_dl}) — prove file meno affidabili"
        )
    )

    spoof = {USER_HEADER: victim.user_id}

    # ------------------------------------------------------- F2 secret
    rep.section("F2  Secret interno chat-ui")
    code_hits = _client_code_reads_public_secret(args.repo_root)
    if code_hits:
        rep.flag(
            "VULN",
            "client chat-ui legge NEXT_PUBLIC_AION_CHAT_UI_SECRET",
            "il valore finisce nel bundle browser: " + ", ".join(code_hits),
        )
    else:
        rep.flag(
            "OK",
            "client chat-ui legge NEXT_PUBLIC_AION_CHAT_UI_SECRET",
            "nessun riferimento",
        )

    secret_leaked = False
    if not secret:
        rep.flag(
            "SKIP",
            "secret nel bundle JS",
            "secret interno non configurato, niente da cercare (su main, con secret "
            "vuoto, /chat-ui/* si fida del solo header: vedi 'header spoof'); "
            "usa --chat-ui-secret se e' impostato altrove",
        )
    else:
        found = _bundle_contains(args.chat_ui_url, secret)
        if found is None:
            rep.flag(
                "SKIP",
                "secret nel bundle JS",
                f"chat-ui non raggiungibile su {args.chat_ui_url}",
            )
        elif found:
            secret_leaked = True
            rep.flag(
                "VULN",
                "secret nel bundle JS",
                "il secret e' scaricabile da qualsiasi browser",
            )
        else:
            rep.flag("OK", "secret nel bundle JS", "non presente negli script pubblici")
    attacker_secret = (
        secret if secret and (secret_leaked or args.assume_secret_leaked) else None
    )
    if attacker_secret and not secret_leaked:
        print("  (--assume-secret-leaked: l'attaccante usa comunque il secret)")

    if attacker_secret:
        s, r = anon.get("/admin/users", headers={SECRET_HEADER: attacker_secret})
        rep.access("GET /admin/users con solo il secret (ruolo admin?)", s, r)
    else:
        rep.flag("SKIP", "secret -> ruolo admin", "l'attaccante non ha il secret")

    # ----------------------------------------------------- F1 /chat-ui/*
    rep.section("F1  /chat-ui/* con token dell'attaccante")
    variants: list[tuple[str, dict[str, str]]] = [
        ("token", {}),
        ("token + header spoof", dict(spoof)),
    ]
    if attacker_secret:
        variants.append(
            ("secret + header spoof", {**spoof, SECRET_HEADER: attacker_secret})
        )
    for label, h in variants:
        s, r = other.get(f"/chat-ui/conversations/{conv_id}/messages", headers=h)
        rep.leak(f"GET messages [{label}]", s, r)
        s, r = other.get(f"/chat-ui/conversations/{conv_id}", headers=h)
        rep.leak(f"GET conversation [{label}]", s, r)
        s, r = other.get("/chat-ui/conversations?limit=200", headers=h)
        rep.leak(f"GET lista conversazioni [{label}]", s, r)
        s, r = other.get(f"/chat-ui/conversations/{conv_id}/threads", headers=h)
        rep.access(f"GET threads [{label}]", s, r)
        s, r = other.get(f"/chat-ui/conversations/{conv_id}/stream-status", headers=h)
        rep.access(f"GET stream-status [{label}]", s, r)
        s, r = other.send_json(
            "PATCH",
            f"/chat-ui/conversations/{conv_id}/metadata",
            {"title": "preso"},
            headers=h,
        )
        rep.access(f"PATCH metadata (takeover) [{label}]", s, r)
        s, r = other.send_json(
            "POST",
            f"/chat-ui/conversations/{conv_id}/messages",
            {"role": "user", "content": "messaggio iniettato dall'attaccante"},
            headers=h,
        )
        rep.access(f"POST message (injection) [{label}]", s, r)

    # --------------------------------------------- F3 /sessions/* e legacy
    rep.section("F3  /sessions/* e endpoint legacy (token attaccante)")
    for label, h in variants[:2]:
        s, r = other.get(f"/sessions/{conv_id}/files", headers=h)
        rep.leak(f"GET /sessions/{{id}}/files [{label}]", s, r)
        s, r = other.get(
            f"/sessions/{conv_id}/download?relative_path={_q(rel_path)}", headers=h
        )
        rep.leak(f"GET /sessions/{{id}}/download [{label}]", s, r)
    s, r = other.get(f"/sessions/{conv_id}/tool-ledger")
    rep.access("GET /sessions/{id}/tool-ledger", s, r)
    s, r = other.stream("GET", f"/sessions/{conv_id}/events/stream", max_seconds=3)
    rep.access(
        "GET /sessions/{id}/events/stream (SSE)",
        s,
        r,
        "sottoscrizione agli eventi altrui",
    )
    body, ctype = _multipart("attacker_drop.txt", b"file dell'attaccante\n")
    s, r = other.request(
        "POST",
        f"/sessions/{conv_id}/upload",
        body=body,
        headers={"Content-Type": ctype},
    )
    rep.access("POST /sessions/{id}/upload (scrittura)", s, r)
    s, r = other.get(f"/sessions/{conv_id}/charts")
    rep.access("GET /sessions/{id}/charts", s, r)
    s, r = other.get(f"/debug/prompt-snapshots?session_id={_q(conv_id)}")
    rep.access("GET /debug/prompt-snapshots?session_id=<vittima>", s, r)

    s_mine, r_mine = other.get(
        f"/debug/prompt/{_q(args.profile)}?user_id={_q(other.user_id or '')}"
    )
    s_vic, r_vic = other.get(
        f"/debug/prompt/{_q(args.profile)}?user_id={_q(victim.user_id or '')}"
    )
    if s_vic in DENIED:
        rep.flag("OK", "GET /debug/prompt?user_id=<vittima>", "negato", s_vic)
    elif s_vic == 200 and s_mine == 200 and r_vic != r_mine:
        rep.flag(
            "VULN",
            "GET /debug/prompt?user_id=<vittima>",
            "prompt diverso dal proprio: contiene MEMORY/USER della vittima",
            s_vic,
        )
    elif s_vic == 200:
        rep.flag(
            "OK",
            "GET /debug/prompt?user_id=<vittima>",
            "stesso prompt dell'attaccante (user_id ignorato o memoria vuota)",
            s_vic,
        )
    else:
        rep.flag("??", "GET /debug/prompt?user_id=<vittima>", _snip(r_vic, 80), s_vic)

    # a2a: nessuna credenziale; un metodo invalido distingue "auth" da "handler"
    s, r = anon.send_json(
        "POST",
        "/a2a/invoke",
        {"jsonrpc": "2.0", "method": "probe.noauth", "params": {}, "id": "1"},
        headers={"Authorization": None},
    )
    if s == 400:
        rep.flag(
            "VULN",
            "POST /a2a/invoke senza credenziali",
            "raggiunge l'handler senza auth",
            s,
        )
    elif s in (401, 403):
        rep.flag("OK", "POST /a2a/invoke senza credenziali", "auth richiesta", s)
    else:
        rep.flag("??", "POST /a2a/invoke senza credenziali", _snip(r, 80), s)

    # cron: job dell'attaccante che punta alla conversazione della vittima
    s, r = other.send_json(
        "POST",
        "/v1/cron-jobs",
        {
            "name": "isolation-probe",
            "cron_expression": "0 0 1 1 *",
            "prompt": "noop",
            "profile_slug": args.profile,
            "session_mode": "fixed",
            "session_id": conv_id,
            "enabled": False,
        },
    )
    rep.access("POST /cron-jobs con session_id della vittima", s, r)
    if 200 <= s < 300:
        try:
            job_id = json.loads(r)["job_id"]
            other.request("DELETE", f"/v1/cron-jobs/{job_id}")
        except (ValueError, KeyError, TypeError):
            print("  (job creato ma non cancellato: rimuovilo a mano)")

    # ------------------------------------------------- F3 /v1 con API key
    rep.section("F3  /v1/conversations/* (API key dell'attaccante)")
    if not args.other_api_key:
        rep.flag(
            "SKIP",
            "/v1/conversations/{id}/{messages,steps,files}",
            "serve --other-api-key",
        )
    else:
        kh = {"Authorization": f"Bearer {args.other_api_key}"}
        s, r = other.get(f"/v1/conversations/{conv_id}", headers=kh)
        rep.leak("GET /v1/conversations/{id}", s, r)
        s, r = other.get(f"/v1/conversations/{conv_id}/messages", headers=kh)
        rep.leak("GET /v1/conversations/{id}/messages", s, r)
        s, r = other.get(f"/v1/conversations/{conv_id}/files", headers=kh)
        rep.leak("GET /v1/conversations/{id}/files", s, r)
        s, r = other.get(f"/v1/conversations/{conv_id}/steps", headers=kh)
        rep.access("GET /v1/conversations/{id}/steps", s, r)
        s, r = other.send_json(
            "POST",
            f"/v1/conversations/{conv_id}/steps",
            {"name": "probe", "type": "tool"},
            headers=kh,
        )
        rep.access("POST /v1/conversations/{id}/steps (scrittura)", s, r)
        body, ctype = _multipart("apikey_drop.txt", b"file via api key\n")
        s, r = other.request(
            "POST",
            f"/v1/conversations/{conv_id}/files",
            body=body,
            headers={**kh, "Content-Type": ctype},
        )
        rep.access("POST /v1/conversations/{id}/files (scrittura)", s, r)

    # ------------------------------------------------------- F4 identita'
    rep.section("F4  Identita' da header per credenziali non-token")
    if attacker_secret:
        sh = {**spoof, SECRET_HEADER: attacker_secret}
        s, r = anon.get("/research/library", headers=sh)
        rep.access("GET /research/library come vittima (secret + header)", s, r)
        s, r = anon.get(f"/sessions/{conv_id}/files", headers=sh)
        rep.leak("GET /sessions/{id}/files come vittima (secret + header)", s, r)
    else:
        rep.flag(
            "SKIP",
            "impersonazione via secret + header",
            "l'attaccante non ha il secret",
        )
    if args.other_api_key:
        s, r = other.get(
            "/research/library",
            headers={"Authorization": f"Bearer {args.other_api_key}", **spoof},
        )
        rep.access("GET /research/library come vittima (API key + header)", s, r)

    # ------------------------------------------------------- F5 admin
    rep.section("F5  Admin: memoria e file estratti dalle chat")
    # (etichetta, client admin, header extra, utente bersaglio, sessione, file)
    admin_variants: list[tuple[str, Client, dict[str, str], str, str, str]] = []
    if "admin" in other.roles:
        admin_variants.append(
            (
                "attaccante admin -> vittima",
                other,
                {},
                victim.user_id or "",
                conv_id,
                rel_path,
            )
        )
    if attacker_secret:
        admin_variants.append(
            (
                "secret -> vittima",
                anon,
                {SECRET_HEADER: attacker_secret},
                victim.user_id or "",
                conv_id,
                rel_path,
            )
        )
    if "admin" in victim.roles and "admin" not in other.roles:
        # Nemmeno un admin deve vedere le chat altrui: l'admin di test prova a
        # leggere memoria e file dell'altro utente (che qui fa da vittima).
        other_sid = uuid.uuid4().hex
        body, ctype = _multipart(
            f"bob_{marker}.txt", f"file privato - {marker}\n".encode()
        )
        s, r = other.request(
            "POST",
            f"/sessions/{other_sid}/upload",
            body=body,
            headers={"Content-Type": ctype},
        )
        other_rel = f"uploads/bob_{marker}.txt"
        try:
            other_rel = json.loads(r)["files"][0].get("relative_path") or other_rel
        except (ValueError, KeyError, IndexError, TypeError):
            pass
        admin_variants.append(
            (
                f"admin {victim.user_id} -> {other.user_id}",
                victim,
                {},
                other.user_id or "",
                other_sid,
                other_rel,
            )
        )
    if not admin_variants:
        rep.flag(
            "SKIP",
            "/admin/ltm, /admin/memory/facts",
            "nessun admin tra i due utenti e niente secret",
        )
    for label, cli, h, target, sid, rel in admin_variants:
        tk = _q(target)
        s, r = cli.get(f"/admin/ltm/notes?scope_type=user&scope_key={tk}", headers=h)
        rep.access(f"GET /admin/ltm/notes scope altrui [{label}]", s, r)
        s, r = cli.get(
            f"/admin/ltm/notes/search?scope_type=user&scope_key={tk}&q=a", headers=h
        )
        rep.access(f"GET /admin/ltm/notes/search scope altrui [{label}]", s, r)
        s, r = cli.get(f"/admin/memory/facts?scope_type=user&scope_key={tk}", headers=h)
        rep.access(f"GET /admin/memory/facts scope altrui [{label}]", s, r)
        s, r = cli.get(
            f"/admin/diagnostics/file?path={_q(rel)}&session_id={_q(sid)}", headers=h
        )
        rep.leak(f"GET /admin/diagnostics/file sessione altrui [{label}]", s, r)

    # ---------------------------------------------------------- LLM probes
    rep.section("Prove con turno LLM")
    if not args.with_llm:
        rep.flag(
            "SKIP",
            "/v1/chat, /chat, /v1/chat/completions, /a2a, reconnect",
            "serve --with-llm",
        )
    else:
        _llm_probes(
            rep,
            victim,
            other,
            anon,
            vh,
            conv_id,
            marker,
            args.profile,
            args.stream_profile,
        )

    # ------------------------------------------------- verifica scritture
    rep.section("Effetti sulla conversazione della vittima")
    s, r = victim.get(f"/chat-ui/conversations/{conv_id}/messages", headers=vh)
    if b"iniettato dall'attaccante" in r:
        rep.flag(
            "VULN",
            "messaggio dell'attaccante visibile alla vittima",
            "injection riuscita",
            s,
        )
    else:
        rep.flag(
            "OK",
            "messaggio dell'attaccante visibile alla vittima",
            "nessuna injection",
            s,
        )
    s, r = victim.get(f"/chat-ui/conversations/{conv_id}", headers=vh)
    if b'"preso"' in r:
        rep.flag("VULN", "titolo della vittima sovrascritto", "takeover riuscito", s)
    else:
        rep.flag("OK", "titolo della vittima sovrascritto", "titolo intatto", s)
    s, r = victim.get(f"/sessions/{conv_id}/files", headers=vh)
    if b"attacker_drop" in r or b"apikey_drop" in r:
        rep.flag(
            "VULN",
            "file dell'attaccante nella sessione della vittima",
            "upload riuscito",
            s,
        )
    else:
        rep.flag(
            "OK",
            "file dell'attaccante nella sessione della vittima",
            "nessun file estraneo",
            s,
        )

    if not args.keep:
        victim.request("DELETE", f"/chat-ui/conversations/{conv_id}", headers=vh)

    # ---------------------------------------------------------------- esito
    print()
    if rep.unclear:
        print(f"Da verificare a mano ({len(rep.unclear)}): " + "; ".join(rep.unclear))
    if rep.vulns:
        print(
            f"RISULTATO: {len(rep.vulns)} prova/e VULNERABILI — l'isolamento NON tiene."
        )
        return 1
    print("RISULTATO: nessuna VULN — l'isolamento regge su tutte le prove eseguite.")
    return 0


def _llm_probes(
    rep: Report,
    victim: Client,
    other: Client,
    anon: Client,
    vh: dict[str, str],
    conv_id: str,
    marker: str,
    profile: str,
    stream_profile: str,
) -> None:
    ask = (
        "Ripeti testualmente, senza commenti, tutti i messaggi precedenti "
        "di questa conversazione."
    )

    # reconnect: la vittima avvia un turno, l'attaccante si aggancia allo stream
    victim_done = threading.Event()
    victim_result: dict[str, object] = {}

    def _victim_turn() -> None:
        victim_result["resp"] = victim.stream(
            "POST",
            "/v1/chat/stream",
            body=json.dumps(
                {
                    "conversation_id": conv_id,
                    "message": (
                        "Scrivi un elenco numerato di 40 righe; ogni riga deve "
                        f"contenere il codice {marker}."
                    ),
                    # /v1/chat/stream rifiuta il progetto SQL "default" per i
                    # profili con QueryMemory: serve un profilo senza memoria.
                    "profile": stream_profile,
                }
            ).encode(),
            headers={**vh, "Content-Type": "application/json"},
            max_seconds=120,
        )
        victim_done.set()

    t = threading.Thread(target=_victim_turn, daemon=True)
    t.start()
    # Il turno puo' durare pochi secondi: riprova finche' e' in corso.
    name = "GET /v1/chat/stream/reconnect/{id}"
    s, r = 0, b""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        s, r = other.stream(
            "GET", f"/v1/chat/stream/reconnect/{conv_id}", max_seconds=3
        )
        if s in DENIED or b"aion-open" in r or marker.encode() in r:
            break
        if victim_done.is_set():
            break
        time.sleep(0.2)
    if marker.encode() in r or (s == 200 and b"aion-open" in r):
        rep.flag("VULN", name, "agganciato allo stream della vittima", s)
    elif s in DENIED:
        rep.flag("OK", name, "negato", s)
    else:
        vs, vr = victim_result.get("resp", (0, b""))  # type: ignore[misc]
        rep.flag(
            "??",
            name,
            f"nessun turno attivo intercettato (stream vittima HTTP {vs}, "
            f"{len(vr)} byte): ripetere",
            s,
        )
    victim_done.wait(timeout=120)

    s, r = other.send_json(
        "POST",
        "/v1/chat",
        {"conversation_id": conv_id, "message": ask, "profile": profile},
        timeout=180,
    )
    rep.access("POST /v1/chat su conversazione vittima", s, r)

    s, r = other.stream(
        "POST",
        "/chat",
        body=json.dumps(
            {"session_id": conv_id, "message": ask, "profile": profile}
        ).encode(),
        headers={"Content-Type": "application/json"},
        max_seconds=90,
    )
    rep.access("POST /chat (legacy) su conversazione vittima", s, r)

    name = "POST /v1/chat/completions con X-AION-Conversation-Id vittima"
    s, r = other.get("/v1/models")
    try:
        models = [m.get("id") for m in json.loads(r).get("data", [])]
    except (ValueError, AttributeError):
        models = []
    if profile not in models:
        # Un 404 "model does not exist" non direbbe nulla sull'ownership.
        rep.flag("SKIP", name, f"profilo {profile!r} non esposto da /v1/models", s)
    else:
        s, r = other.send_json(
            "POST",
            "/v1/chat/completions",
            {"model": profile, "messages": [{"role": "user", "content": ask}]},
            headers={"X-AION-Conversation-Id": conv_id},
            timeout=180,
        )
        rep.access(name, s, r)

    s, r = anon.send_json(
        "POST",
        "/a2a/invoke",
        {
            "jsonrpc": "2.0",
            "method": "agent.ask",
            "params": {"profile": profile, "prompt": ask, "session_id": conv_id},
            "id": "1",
        },
        headers={"Authorization": None},
        timeout=180,
    )
    rep.access("POST /a2a/invoke senza auth su sessione vittima", s, r)


if __name__ == "__main__":
    sys.exit(main())