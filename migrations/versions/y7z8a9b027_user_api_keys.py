"""API key per-utente: users.can_create_api_keys/max_api_keys/api_key_max_ttl_days,
api_keys.user_id, indice unique su api_keys.hash; revoca le chiavi senza proprietario.

Revision ID: y7z8a9b027
Revises: x6y7z8a026
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "y7z8a9b027"
down_revision: Union[str, None] = "x6y7z8a026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USER_COLS = [
    (
        "can_create_api_keys",
        lambda: sa.Column("can_create_api_keys", sa.Boolean(), server_default="0", nullable=False),
    ),
    (
        "max_api_keys",
        lambda: sa.Column("max_api_keys", sa.Integer(), server_default="5", nullable=False),
    ),
    (
        "api_key_max_ttl_days",
        lambda: sa.Column("api_key_max_ttl_days", sa.Integer(), server_default="90", nullable=False),
    ),
]

# FK non dichiarata a livello DB (SQLite non supporta ADD CONSTRAINT); la
# cancellazione delle chiavi di un utente è esplicita in ``delete_user``.
_API_KEY_COLS = [
    ("user_id", lambda: sa.Column("user_id", sa.String(64), nullable=True)),
]

_INDEXES = [
    ("ix_api_keys_user_id", ["user_id"], False),
    ("ux_api_keys_hash", ["hash"], True),
]


def _add_missing(table: str, cols) -> None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    for name, factory in cols:
        if name not in existing:
            op.add_column(table, factory())


def _drop_existing(table: str, cols) -> None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    to_drop = [n for n, _ in cols if n in existing]
    if not to_drop:
        return
    with op.batch_alter_table(table) as batch:
        for n in to_drop:
            batch.drop_column(n)


def upgrade() -> None:
    _add_missing("users", _USER_COLS)
    _add_missing("api_keys", _API_KEY_COLS)
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("api_keys"):
        return
    existing = {ix["name"] for ix in inspector.get_indexes("api_keys")}
    for name, cols, unique in _INDEXES:
        if name not in existing:
            op.create_index(name, "api_keys", cols, unique=unique)
    # Le chiavi pre-esistenti non hanno proprietario (e usano hash bcrypt):
    # non sono più valide, le marchiamo revocate per chiarezza nello storico.
    op.get_bind().execute(
        sa.text(
            "UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP "
            "WHERE user_id IS NULL AND revoked_at IS NULL"
        )
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("api_keys"):
        existing = {ix["name"] for ix in inspector.get_indexes("api_keys")}
        for name, _, _ in _INDEXES:
            if name in existing:
                op.drop_index(name, table_name="api_keys")
    _drop_existing("api_keys", _API_KEY_COLS)
    _drop_existing("users", _USER_COLS)
