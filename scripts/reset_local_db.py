#!/usr/bin/env python3
"""Riporta il DB unificato locale (SQLite) allo stato di un progetto appena avviato.

Uso (dalla root del repo, con il backend FERMO):

    python scripts/reset_local_db.py            # chiede conferma
    python scripts/reset_local_db.py --yes      # senza conferma
    python scripts/reset_local_db.py --all-data # anche sessioni, memorie, utenti su disco

Passi:
  1. backup coerente del DB (incluso il WAL) in ``data/_backups/``
     (``--no-backup`` per saltarlo);
  2. rimozione di ``aion.db`` / ``-wal`` / ``-shm``;
  3. ricreazione dello schema (bootstrap + migrazioni Alembic), come
     ``scripts/init_unified_db.py``.

L'admin di default (``AION_SETUP_ADMIN_DEFAULT_IDENTIFIER`` /
``AION_SETUP_ADMIN_DEFAULT_PASSWORD``, default admin/admin) viene ricreato al
primo avvio del backend. ``.env`` e ``data/runtime.env`` NON vengono toccati.
Solo per DB SQLite: per altri backend il reset va fatto sul server DB.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import socket
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Dati runtime rimossi con --all-data (generati dall'uso, ricreati al bisogno).
RUNTIME_DATA_DIRS = (
    "data/sessions",
    "data/users",
    "data/mempalace",
    "data/plan_execution",
    "data/deep_research",
    "data/cache",
)


def _sqlite_path() -> Path:
    url = os.getenv("AION_DB_URL", "sqlite+aiosqlite:///data/aion.db")
    if not url.startswith("sqlite"):
        sys.exit(f"[error] AION_DB_URL non e' SQLite ({url}): reset non supportato.")
    raw = url.split(":///", 1)[1]
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def _backend_running() -> bool:
    port = int(os.getenv("AION_API_PORT", "8001"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _backup(db: Path) -> Path:
    out_dir = ROOT / "data" / "_backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"aion_db_before_reset_{time.strftime('%Y%m%d_%H%M%S')}.db"
    # API backup di sqlite: copia coerente che include le pagine ancora nel WAL.
    src = sqlite3.connect(db)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


async def _recreate() -> None:
    from src.data.bootstrap import ensure_bootstrap_schema, patch_sqlite_schema_drift
    from src.data.engine import init_engine
    from src.data.migrations import run_migrations

    eng = init_engine()
    await ensure_bootstrap_schema(eng)
    run_migrations()
    await patch_sqlite_schema_drift(eng)
    await eng.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", "-y", action="store_true", help="non chiedere conferma")
    ap.add_argument("--no-backup", action="store_true", help="non salvare una copia del DB")
    ap.add_argument(
        "--all-data",
        action="store_true",
        help="rimuove anche i dati runtime su disco: " + ", ".join(RUNTIME_DATA_DIRS),
    )
    ap.add_argument("--force", action="store_true", help="procedi anche se il backend risponde")
    args = ap.parse_args()

    os.chdir(ROOT)
    from src import aion_env  # noqa: F401  carica .env (AION_DB_URL, ...)

    db = _sqlite_path()
    if _backend_running() and not args.force:
        sys.exit(
            "[error] Il backend sembra attivo sulla porta "
            f"{os.getenv('AION_API_PORT', '8001')}: fermalo prima (o usa --force)."
        )

    print(f"DB: {db}")
    if args.all_data:
        print("Dati runtime da rimuovere: " + ", ".join(RUNTIME_DATA_DIRS))
    if not args.yes:
        answer = input("Tutti i dati (utenti, chat, impostazioni auth/SSO) verranno persi. Continuare? [y/N] ")
        if answer.strip().lower() not in ("y", "yes", "s", "si"):
            sys.exit("Annullato.")

    if db.exists() and not args.no_backup:
        print(f"[1/3] Backup: {_backup(db)}")
    else:
        print("[1/3] Backup saltato.")

    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    if args.all_data:
        for rel in RUNTIME_DATA_DIRS:
            shutil.rmtree(ROOT / rel, ignore_errors=True)
    print("[2/3] DB rimosso.")

    asyncio.run(_recreate())
    print("[3/3] Schema ricreato.")
    print(
        "\nFatto. Avvia il backend: l'admin di default verra' ricreato "
        f"({os.getenv('AION_SETUP_ADMIN_DEFAULT_IDENTIFIER', 'admin')} / password di default)."
    )


if __name__ == "__main__":
    main()
