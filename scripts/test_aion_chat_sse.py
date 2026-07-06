#!/usr/bin/env python3
"""
Diagnostica POST /chat (SSE): tempo fino agli header HTTP e primi byte del body.

Uso (API su localhost:8001):
  ./scripts/test_aion_chat_sse.py
  ./scripts/test_aion_chat_sse.py http://127.0.0.1:8001 "Generic Assistant"

Richiede: httpx (presente in requirements.txt del progetto).
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid


def main() -> int:
    p = argparse.ArgumentParser(description="Test SSE POST /chat timing")
    p.add_argument(
        "base_url",
        nargs="?",
        default="http://127.0.0.1:8001",
        help="Base API senza trailing slash",
    )
    p.add_argument(
        "profile", nargs="?", default="Generic Assistant", help="Nome profilo YAML"
    )
    p.add_argument(
        "--message", default="Say hello in one short sentence.", help="Messaggio utente"
    )
    p.add_argument(
        "--user-id", default="default", dest="user_id", help="Header X-AION-User-Id"
    )
    p.add_argument(
        "--max-bytes",
        type=int,
        default=8000,
        help="Massimo byte da leggere dallo stream poi esci",
    )
    args = p.parse_args()

    try:
        import httpx
    except ImportError:
        print("Installa httpx: pip install httpx", file=sys.stderr)
        return 2

    base = args.base_url.rstrip("/")
    url = f"{base}/chat"
    session_id = str(uuid.uuid4())
    payload = {
        "message": args.message,
        "session_id": session_id,
        "profile": args.profile,
        "user_id": args.user_id,
        "reasoning_effort": "min",
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-AION-User-Id": args.user_id,
    }

    connect_timeout = 10.0
    read_timeout = 120.0
    timeout = httpx.Timeout(read_timeout, connect=connect_timeout)

    print(f"POST {url}")
    print(f"session_id={session_id} profile={args.profile!r}")

    t0 = time.perf_counter()
    first_headers_at: float | None = None
    first_body_at: float | None = None
    total = 0

    try:
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", url, json=payload, headers=headers) as r:
                first_headers_at = time.perf_counter()
                print(
                    f"HTTP status={r.status_code} (+{(first_headers_at - t0) * 1000:.1f} ms from start)"
                )
                if r.status_code != 200:
                    body = r.read()
                    print(body.decode(errors="replace")[:2000])
                    return 1

                for chunk in r.iter_bytes(chunk_size=4096):
                    if first_body_at is None and chunk:
                        first_body_at = time.perf_counter()
                        print(
                            f"First body chunk (+{(first_body_at - t0) * 1000:.1f} ms from start, "
                            f"+{(first_body_at - first_headers_at) * 1000:.1f} ms after headers)"
                        )
                        preview = (
                            chunk[:240].decode(errors="replace").replace("\r", "\\r")
                        )
                        print(f"Raw preview: {preview!r}")
                    total += len(chunk)
                    if total >= args.max_bytes:
                        print(f"Stopping after {total} bytes (see --max-bytes)")
                        break

    except httpx.ConnectError as e:
        print(
            f"CONNECT FAILED after {(time.perf_counter() - t0) * 1000:.1f} ms: {e}",
            file=sys.stderr,
        )
        print(
            "Verifica che l'API sia in ascolto e l'URL sia raggiungibile (es. http://127.0.0.1:8001).",
            file=sys.stderr,
        )
        return 1
    except httpx.ReadTimeout:
        print(
            f"READ TIMEOUT after {(time.perf_counter() - t0) * 1000:.1f} ms",
            file=sys.stderr,
        )
        return 1

    elapsed = time.perf_counter() - t0
    print(f"Done: read ~{total} bytes in {elapsed * 1000:.1f} ms total")
    if first_headers_at and (first_headers_at - t0) > 3.0:
        print(
            "Note: headers took >3s — prima del fix backend, get_agent bloccava prima dello stream; "
            "dopo il fix dovresti vedere header quasi subito e MCP warm nei primi chunk/SSE.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
