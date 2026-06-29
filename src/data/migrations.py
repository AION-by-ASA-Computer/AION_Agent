"""Alembic migration runner per il DB unificato.

Note:
- ``AION_DB_URL`` puo' usare il driver async (``sqlite+aiosqlite``,
  ``postgresql+asyncpg``). Alembic e' sincrono: convertiamo l'URL al
  driver sync equivalente prima di passarlo ad Alembic.
- Su DB gia' bootstrappato da :func:`src.data.bootstrap.ensure_bootstrap_schema`
  (che crea le tabelle dal modello CORRENTE) la migration di baseline
  ``15a42b5aff9f`` non e' applicabile (tenterebbe ALTER COLUMN su una
  schema gia' allineato e su SQLite questo non e' supportato). In quel
  caso facciamo uno *stamp head* invece dell'upgrade: marca tutte le
  revision come applicate senza eseguirle, e gli upgrade futuri
  partiranno dalle migration successive (gia' idempotenti).
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

logger = logging.getLogger("aion.data.migrations")


def _to_sync_db_url(url: str) -> str:
    """Converte un URL DB async nel driver sync equivalente.

    Idempotente sugli URL gia' sync.
    """
    if not url:
        return url
    url = re.sub(r"^sqlite\+aiosqlite(://|:)", r"sqlite\1", url)
    url = re.sub(r"^postgresql\+asyncpg(://|:)", r"postgresql+psycopg2\1", url)
    url = re.sub(r"^mysql\+aiomysql(://|:)", r"mysql+pymysql\1", url)
    return url


# Tabelle "core" prodotte da ensure_bootstrap_schema(): se ne troviamo
# almeno una di queste E alembic_version e' vuota, assumiamo che il DB
# sia stato creato da Base.metadata.create_all() ed e' gia' allineato
# alla revision corrente -> stamp head.
_CORE_TABLES = ("messages", "conversations", "audit_log", "users", "tenants")


def _needs_stamp_baseline(sync_url: str) -> bool:
    """True se il DB ha gia' le tabelle core ma alembic_version e' vuoto."""
    try:
        engine = create_engine(sync_url)
        try:
            with engine.connect() as conn:
                insp = inspect(conn)
                existing = set(insp.get_table_names())
                if not any(t in existing for t in _CORE_TABLES):
                    return False
                ctx = MigrationContext.configure(conn)
                current = ctx.get_current_revision()
                return current is None
        finally:
            engine.dispose()
    except Exception as e:
        logger.warning("Impossibile ispezionare lo stato del DB per lo stamp: %s", e)
        return False


def run_migrations() -> None:
    """Esegue le migrazioni Alembic all'avvio.

    Strategia:
    1. Converte ``AION_DB_URL`` da async a sync (Alembic e' sincrono).
    2. Se il DB ha gia' le tabelle core E ``alembic_version`` e' vuoto,
       esegue ``alembic stamp head`` invece di ``upgrade head``.
    3. Altrimenti esegue ``alembic upgrade head`` normalmente.
    """
    try:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        ini_path = os.path.join(base_path, "alembic.ini")
        if not os.path.exists(ini_path):
            logger.warning("alembic.ini non trovato in %s. Skip migrazioni.", ini_path)
            return

        alembic_cfg = Config(ini_path)
        alembic_cfg.set_main_option(
            "script_location", os.path.join(base_path, "migrations")
        )

        raw_db_url = (os.getenv("AION_DB_URL") or "").strip()
        sync_db_url = _to_sync_db_url(raw_db_url)
        if sync_db_url:
            alembic_cfg.set_main_option("sqlalchemy.url", sync_db_url)
            scheme = urlparse(sync_db_url).scheme or sync_db_url
            logger.info("Alembic target DB driver: %s", scheme)
        else:
            sync_db_url = alembic_cfg.get_main_option("sqlalchemy.url") or ""

        if sync_db_url and _needs_stamp_baseline(sync_db_url):
            try:
                script = ScriptDirectory.from_config(alembic_cfg)
                head_rev = script.get_current_head()
            except Exception:
                head_rev = "head"
            logger.info(
                "DB gia' bootstrappato da metadata.create_all() e alembic_version vuoto: "
                "eseguo 'alembic stamp %s' invece di 'upgrade head'.",
                head_rev,
            )
            command.stamp(alembic_cfg, "head")
            logger.info("Alembic stamp completato: DB marcato come up-to-date.")
            return

        logger.info("Esecuzione migrazioni DB (alembic upgrade head)...")
        command.upgrade(alembic_cfg, "head")
        logger.info("DB aggiornato correttamente.")
    except Exception as e:  # noqa: BLE001
        logger.error("Errore durante le migrazioni Alembic: %s", e)
