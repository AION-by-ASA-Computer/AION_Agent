"""Migrazione ``a9b0c1d029``: crea le 4 tabelle (idempotente) e le rimuove."""

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


def _load():
    path = _ROOT / "migrations/versions/a9b0c1d029_whatsapp_channel.py"
    spec = importlib.util.spec_from_file_location("mig_a9b0c1d029", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(eng, fn_name):
    mod = _load()
    with eng.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn_name)()


def test_upgrade_downgrade(tmp_path):
    mod = _load()
    assert mod.down_revision == "z8a9b0c028"
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
    insp = inspect(eng)
    for table in TABLES:
        orm_cols = {c.name for c in Base.metadata.tables[table].columns}
        mig_cols = {c["name"] for c in insp.get_columns(table)}
        assert orm_cols == mig_cols, table
