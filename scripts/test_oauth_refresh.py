#!/usr/bin/env python3
"""
Script di verifica: forza un token khub vicino alla scadenza e controlla
che _refresh_expiring_oauth_tokens lo riconosca e riavvii il worker.

Eseguire con il backend AION attivo:
    python scripts/test_oauth_refresh.py
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone

# Bootstrap AION
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import src.aion_env  # noqa: F401 — MUST be first

async def main():
    from src.mcp_manager import mcp_manager
    from src.runtime.credential_store import (
        _get_credential_row, set_credential,
        OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS,
    )
    from src.identity import sanitize_user_id

    user_id = os.getenv("TEST_USER_ID", "admin")
    server_slug = os.getenv("TEST_SERVER_SLUG", "khub")
    tenant_id = os.getenv("TEST_TENANT_ID", "default")

    print(f"\n{'='*60}")
    print(f"TEST: OAuth token refresh + worker restart")
    print(f"user={user_id}  server={server_slug}  tenant={tenant_id}")
    print(f"{'='*60}\n")

    # 1) Leggi il token corrente dal DB
    row = await _get_credential_row(user_id, server_slug, "OAUTH_TOKEN", tenant_id=tenant_id)
    if not row:
        print("NO TOKEN: nessun token OAUTH_TOKEN trovato per questo utente/server.")
        print("   Assicurati di aver fatto il login OAuth in AION prima di questo test.")
        return

    current_expires = row.expires_at
    print(f"Token trovato nel DB")
    print(f"   expires_at attuale: {current_expires}")
    print(f"   OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS: {OAUTH_TOKEN_EXPIRY_BUFFER_SECONDS}s")

    # 2) Controlla lo stato del pool
    pool_key = f"__user__{sanitize_user_id(user_id)}__{tenant_id}"
    print(f"\n--- Pool status ---")
    print(f"Pool key: {pool_key}")
    workers_for_server = [
        (sid, sname) for (sid, sname) in mcp_manager._pool
        if sname == server_slug and sid == pool_key
    ]
    print(f"Worker attivi per {server_slug}: {len(workers_for_server)}")

    # 3) Simula token in scadenza imminente (ora + 30s, meno del buffer)
    fake_expires = datetime.now(timezone.utc) + timedelta(seconds=30)
    print(f"\n--- Simulazione scadenza imminente ---")
    print(f"Impostazione expires_at a: {fake_expires} (+30s da adesso)")
    # Devo decifrare il valore per ripassarlo
    from src.runtime.credential_store import decrypt_value
    plaintext_token = decrypt_value(row.value_encrypted)
    await set_credential(
        user_id, server_slug, "OAUTH_TOKEN",
        plaintext_token,
        tenant_id=tenant_id,
        expires_at=fake_expires,
    )
    print("expires_at aggiornato nel DB")

    # 4a) _refresh_expiring_oauth_tokens agisce solo su worker già nel pool
    print(f"\n--- Esecuzione _refresh_expiring_oauth_tokens ---")
    if workers_for_server:
        await mcp_manager._refresh_expiring_oauth_tokens()
    else:
        print("(nessun worker nel pool — bypasso _refresh_expiring_oauth_tokens)")
        print("Test diretto del refresh chain (credential_store.refresh_oauth_access_token)...")
        from src.runtime.credential_store import refresh_oauth_access_token
        new_token = await refresh_oauth_access_token(user_id, server_slug, tenant_id=tenant_id)
        if new_token:
            print(f"OK: refresh_oauth_access_token ha restituito un nuovo token")
        else:
            print("FAIL: refresh_oauth_access_token ha restituito None — controlla i log")

    print("\n--- Post-refresh status ---")
    row_after = await _get_credential_row(user_id, server_slug, "OAUTH_TOKEN", tenant_id=tenant_id)
    # Normalizza entrambe le date a UTC per il confronto
    from src.runtime.credential_store import _normalize_expiry
    fake_expires_aware = fake_expires if fake_expires.tzinfo else fake_expires.replace(tzinfo=timezone.utc)
    if row_after:
        expires_after_aware = _normalize_expiry(row_after.expires_at)
        print(f"Token nel DB dopo refresh: expires_at={row_after.expires_at}")
        if expires_after_aware and expires_after_aware > fake_expires_aware:
            print("TOKEN RINNOVATO CORRETTAMENTE (expires_at aumentato)")
        else:
            print("ATTENZIONE: expires_at invariato — controlla i log del backend")
    else:
        print("Token eliminato — refresh_token scaduto, rifare il login")

    workers_after = [
        (sid, sname) for (sid, sname) in mcp_manager._pool
        if sname == server_slug and sid == pool_key
    ]
    print(f"Worker nel pool dopo refresh: {len(workers_after)}")
    if len(workers_for_server) > 0 and len(workers_after) == 0:
        print("Vecchio worker killato (verra' rispawnato alla prossima richiesta)")

    print(f"\n{'='*60}")
    print("TEST COMPLETATO")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())

