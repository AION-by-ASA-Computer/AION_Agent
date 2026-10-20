#!/usr/bin/env python3
"""Verifica di isolamento: un utente non deve leggere le conversazioni altrui.

Lo script parla con il backend AION in esecuzione usando solo la stdlib.

Passi:
1. login di due account (la "vittima" e il "secondo utente");
2. la vittima crea una conversazione, salva un messaggio con un marker
   segreto e carica un file con lo stesso marker;
3. il secondo utente prova ad accedere a quella conversazione in piu' modi;
   lo script cerca il marker nelle risposte.

Per ogni prova stampa:
  LEAK   il backend ha restituito dati della vittima (regressione!)
  OK     accesso negato / dati non visibili (comportamento atteso)

Uso:
  python scripts/security/check_conversation_isolation.py \
    --base-url http://localhost:8001 \
    --victim-user alice --victim-pass '...' \
    --other-user  bob   --other-pass  '...'

Exit code 0 se nessun LEAK, 1 se almeno un LEAK, 2 per errori di setup.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


class Client:
    """Minimo wrapper HTTP attorno a un utente autenticato."""

    def __init__(self, base_url: str, label: str):
        self.base = base_url.rstrip("/")
        self.label = label
        self.token: str | None = None
        self.user_id: str | None = None

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes]:
        url = self.base + path
        hdrs = dict(headers or {})
        if self.token:
            hdrs.setdefault("Authorization", f"Bearer {self.token}")
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise SystemExit(f"[{self.label}] impossibile contattare {url}: {exc}")

    def get(self, path: str, headers: dict[str, str] | None = None):
        return self._request("GET", path, headers=headers)

    def post_json(self, path: str, payload, headers: dict[str, str] | None = None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self._request(
            "POST", path, body=json.dumps(payload).encode(), headers=h
        )

    def patch_json(self, path: str, payload, headers: dict[str, str] | None = None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        return self._request(
            "PATCH", path, body=json.dumps(payload).encode(), headers=h
        )

    def login(self, username: str, password: str) -> None:
        status, raw = self.post_json(
            "/auth/login", {"username": username, "password": password}
        )
        if status != 200:
            raise SystemExit(
                f"[{self.label}] login fallito ({status}): {raw.decode(errors='replace')[:300]}"
            )
        data = json.loads(raw or b"{}")
        if "access_token" not in data:
            raise SystemExit(
                f"[{self.label}] login senza token (MFA attivo?): "
                f"{raw.decode(errors='replace')[:300]}"
            )
        self.token = data["access_token"]
        self.user_id = data.get("user_id")


def _upload_multipart(client: Client, session_id: str, marker: str) -> tuple[int, bytes]:
    """Carica un piccolo file nella sessione (multipart/form-data a mano)."""
    boundary = "----aion-isolation-" + uuid.uuid4().hex
    filename = "secret_note.txt"
    content = f"documento riservato della vittima - {marker}\n".encode()
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            'Content-Disposition: form-data; name="files"; '
            f'filename="{filename}"\r\n'
        ).encode(),
        b"Content-Type: text/plain\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    headers = {
        "Authorization": f"Bearer {client.token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    return client._request(
        "POST", f"/sessions/{session_id}/upload", body=body, headers=headers
    )


def _contains(raw: bytes, marker: str) -> bool:
    return marker.encode() in raw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8001")
    ap.add_argument("--victim-user", required=True)
    ap.add_argument("--victim-pass", required=True)
    ap.add_argument("--other-user", required=True)
    ap.add_argument("--other-pass", required=True)
    args = ap.parse_args()

    marker = "AION-SECRET-" + uuid.uuid4().hex
    victim = Client(args.base_url, "vittima")
    other = Client(args.base_url, "altro")

    print(f"Backend: {args.base_url}")
    print(f"Marker segreto: {marker}\n")

    victim.login(args.victim_user, args.victim_pass)
    other.login(args.other_user, args.other_pass)
    if victim.user_id and victim.user_id == other.user_id:
        raise SystemExit(
            "I due account risolvono allo stesso user_id: usa account distinti."
        )
    print(f"Login OK — vittima={victim.user_id!r} altro={other.user_id!r}\n")

    # --- setup: la vittima crea e popola la conversazione --------------------
    status, raw = victim.post_json(
        "/v1/conversations", {"title": "chat riservata", "profile": "generic_assistant"}
    )
    if status not in (200, 201):
        raise SystemExit(
            f"creazione conversazione fallita ({status}): {raw.decode(errors='replace')[:300]}"
        )
    conv_id = json.loads(raw)["id"]
    print(f"Conversazione vittima: {conv_id}")

    # messaggio con marker, via chat-ui (percorso usato dal client reale)
    status, raw = victim.post_json(
        f"/chat-ui/conversations/{conv_id}/messages",
        {"role": "assistant", "content": f"appunto privato: {marker}"},
    )
    print(f"  messaggio salvato: HTTP {status}")

    # upload con marker nella stessa sessione
    status, raw = _upload_multipart(victim, conv_id, marker)
    print(f"  file caricato: HTTP {status}")
    time.sleep(0.3)

    # sanity: la vittima rivede i propri dati
    s_own, raw_own = victim.get(f"/chat-ui/conversations/{conv_id}/messages")
    if not (s_own == 200 and _contains(raw_own, marker)):
        raise SystemExit(
            "SETUP NON VALIDO: la vittima non rilegge il proprio marker "
            f"(HTTP {s_own}). Controlla profili/DB prima di fidarti dell'esito."
        )
    print("  sanity: la vittima rivede il proprio marker. OK\n")

    # --- attacchi dell'altro utente -----------------------------------------
    print("Prove di accesso dal secondo utente:\n")
    leaks = 0

    def check(name: str, status: int, raw: bytes) -> None:
        nonlocal leaks
        leaked = _contains(raw, marker)
        verdict = "LEAK " if leaked else "OK   "
        if leaked:
            leaks += 1
        snippet = raw.decode(errors="replace").replace("\n", " ")[:120]
        print(f"  [{verdict}] {name}  (HTTP {status})  {snippet}")

    # 1) leggere i messaggi (chat-ui)
    s, r = other.get(f"/chat-ui/conversations/{conv_id}/messages")
    check("GET /chat-ui/.../messages", s, r)

    # 2) metadati conversazione (chat-ui)
    s, r = other.get(f"/chat-ui/conversations/{conv_id}")
    check("GET /chat-ui/conversations/{id}", s, r)

    # 3) messaggi via v1
    s, r = other.get(f"/v1/conversations/{conv_id}/messages")
    check("GET /v1/.../messages", s, r)

    # 4) conversazione via v1
    s, r = other.get(f"/v1/conversations/{conv_id}")
    check("GET /v1/conversations/{id}", s, r)

    # 5) elenco file della sessione
    s, r = other.get(f"/sessions/{conv_id}/files")
    check("GET /sessions/{id}/files", s, r)

    # 6) download diretto del file caricato
    s, r = other.get(
        f"/sessions/{conv_id}/download?relative_path=uploads/secret_note.txt"
    )
    check("GET /sessions/{id}/download", s, r)

    # 7) spoofing header X-AION-User-Id: fingersi la vittima col proprio token
    victim_hdr = {"X-AION-User-Id": victim.user_id or args.victim_user}
    s, r = other.get(
        f"/chat-ui/conversations/{conv_id}/messages", headers=victim_hdr
    )
    check("GET messages + header X-AION-User-Id spoof", s, r)

    # 8) takeover: scrivere sulla conversazione della vittima
    s, r = other.patch_json(
        f"/chat-ui/conversations/{conv_id}/metadata", {"title": "preso"}
    )
    hijacked = s in (200, 204)
    print(
        f"  [{'LEAK ' if hijacked else 'OK   '}] "
        f"PATCH metadata (takeover scrittura)  (HTTP {s})"
    )
    if hijacked:
        leaks += 1

    # --- esito ---------------------------------------------------------------
    print()
    if leaks:
        print(f"RISULTATO: {leaks} prova/e VULNERABILI — l'isolamento NON tiene.")
        return 1
    print("RISULTATO: nessun leak — l'isolamento regge su tutte le prove.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
