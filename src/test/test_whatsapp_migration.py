"""Migrazione ``a9b0c1d029w``: crea le 4 tabelle (idempotente) e le rimuove."""

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

_ROOT = Path(__file__).resolve().parents[2]
TABLES = {
    "whatsapp_channels",
    "whatsapp_identities",
    "whatsapp_link_codes",
    "whatsapp_messages",
}


def _load(rev="a9b0c1d029w", filename="a9b0c1d029w_whatsapp_channel.py"):
    path = _ROOT / "migrations/versions" / filename
    spec = importlib.util.spec_from_file_location(f"mig_{rev}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_PENDING_MEDIA = ("c1d2e3f031", "c1d2e3f031_whatsapp_pending_media.py")


def _run(eng, fn_name, *, thinking_migration=False, migration=None):
    """Run a migration function.

    ``thinking_migration`` selects ``b0c1d2e030``; ``migration`` is an explicit
    ``(revision, filename)`` pair for later revisions.
    """
    if migration is not None:
        mod = _load(*migration)
    elif thinking_migration:
        mod = _load("b0c1d2e030", "b0c1d2e030_whatsapp_thinking_level.py")
    else:
        mod = _load()
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn_name)()


def test_upgrade_downgrade(tmp_path):
    mod = _load()
    assert mod.down_revision == "a9b0c1d029"
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")

    _run(eng, "upgrade")
    insp = inspect(eng)
    assert TABLES <= set(insp.get_table_names())
    ident_uniques = {
        u["name"] for u in insp.get_unique_constraints("whatsapp_identities")
    }
    assert {
        "uq_whatsapp_identities_bsuid",
        "uq_whatsapp_identities_user",
    } <= ident_uniques
    assert "ix_whatsapp_messages_status" in {
        i["name"] for i in insp.get_indexes("whatsapp_messages")
    }

    _run(eng, "upgrade")  # idempotente

    _run(eng, "downgrade")
    assert not TABLES & set(inspect(eng).get_table_names())


def test_migration_matches_models():
    """Stessi nomi di colonna tra modelli ORM e migrazione."""
    from src.data.models import Base

    eng = create_engine("sqlite://")
    _run(eng, "upgrade")
    # Columns added after the table-creation revision (default_thinking_level).
    _run(eng, "upgrade", thinking_migration=True)
    _run(eng, "upgrade", migration=_PENDING_MEDIA)  # pending_attachments_json
    insp = inspect(eng)
    for table in TABLES:
        orm_cols = {c.name for c in Base.metadata.tables[table].columns}
        mig_cols = {c["name"] for c in insp.get_columns(table)}
        assert orm_cols == mig_cols, table


def test_thinking_level_migration(tmp_path):
    """``b0c1d2e030`` adds ``default_thinking_level``: idempotent and reversible."""
    mod = _load("b0c1d2e030", "b0c1d2e030_whatsapp_thinking_level.py")
    assert mod.down_revision == "a9b0c1d029w"
    eng = create_engine(f"sqlite:///{tmp_path}/t.db")

    def cols():
        return {c["name"] for c in inspect(eng).get_columns("whatsapp_channels")}

    # No table yet: the migration is a no-op instead of failing.
    _run(eng, "upgrade", thinking_migration=True)
    assert "whatsapp_channels" not in inspect(eng).get_table_names()

    # batch_alter_table (SQLite drop) reflects the FK targets, which the
    # isolated migration test does not otherwise create.
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)")

    _run(eng, "upgrade")
    assert "default_thinking_level" not in cols()

    _run(eng, "upgrade", thinking_migration=True)
    assert "default_thinking_level" in cols()
    _run(eng, "upgrade", thinking_migration=True)  # idempotent

    _run(eng, "downgrade", thinking_migration=True)
    assert "default_thinking_level" not in cols()
    _run(eng, "downgrade", thinking_migration=True)  # idempotent


def test_pending_media_migration(tmp_path):
    """``c1d2e3f031`` adds ``pending_attachments_json``: idempotent and reversible."""
    mod = _load(*_PENDING_MEDIA)
    assert mod.down_revision == "b0c1d2e030"
    eng = create_engine(f"sqlite:///{tmp_path}/p.db")

    def cols():
        return {c["name"] for c in inspect(eng).get_columns("whatsapp_identities")}

    # No table yet: the migration is a no-op instead of failing.
    _run(eng, "upgrade", migration=_PENDING_MEDIA)
    assert "whatsapp_identities" not in inspect(eng).get_table_names()

    # FK targets reflected by batch_alter_table on the SQLite drop.
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)")

    _run(eng, "upgrade")
    assert "pending_attachments_json" not in cols()

    _run(eng, "upgrade", migration=_PENDING_MEDIA)
    assert "pending_attachments_json" in cols()
    _run(eng, "upgrade", migration=_PENDING_MEDIA)  # idempotent

    _run(eng, "downgrade", migration=_PENDING_MEDIA)
    assert "pending_attachments_json" not in cols()
    _run(eng, "downgrade", migration=_PENDING_MEDIA)  # idempotent
