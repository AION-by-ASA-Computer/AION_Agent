"""Service accounts: ``users.account_type`` ('human' | 'service') and
``users.disabled_at`` (reversible deactivation that rejects the account's API keys).

Existing rows become ``'human'`` through the server default. Idempotent like the
other user-column migrations, because ``ensure_bootstrap_schema`` may already
have added the columns on SQLite (see ``src/data/bootstrap.py``).

Revision ID: g5b6c7d035
Revises: f4a5b6c034
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g5b6c7d035"
down_revision: Union[str, None] = "f4a5b6c034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USER_COLS = [
    (
        "account_type",
        lambda: sa.Column(
            "account_type", sa.String(16), server_default="human", nullable=False
        ),
    ),
    (
        "disabled_at",
        lambda: sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    ),
]

_INDEX = "ix_users_account_type"


def _add_missing(table: str, cols) -> None:
    """Add only the columns that are not there yet (bootstrap may have added them)."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    for name, factory in cols:
        if name not in existing:
            op.add_column(table, factory())


def _drop_existing(table: str, cols) -> None:
    """Drop the given columns when present (batch mode for SQLite)."""
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
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("users"):
        return
    # Index used by the admin lists that split people from service accounts.
    if _INDEX not in {ix["name"] for ix in inspector.get_indexes("users")}:
        op.create_index(_INDEX, "users", ["account_type"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("users"):
        if _INDEX in {ix["name"] for ix in inspector.get_indexes("users")}:
            op.drop_index(_INDEX, table_name="users")
    _drop_existing("users", _USER_COLS)
