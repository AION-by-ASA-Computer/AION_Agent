"""2FA TOTP: auth_settings.totp_required + users.totp_* columns.

Revision ID: v4w5x6y024
Revises: u3v4w5x023
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v4w5x6y024"
down_revision: Union[str, None] = "u3v4w5x023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USER_COLS = [
    ("totp_secret_encrypted", lambda: sa.Column("totp_secret_encrypted", sa.Text(), nullable=True)),
    ("totp_enabled_at", lambda: sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True)),
    ("totp_last_used_step", lambda: sa.Column("totp_last_used_step", sa.Integer(), nullable=True)),
    (
        "totp_failed_count",
        lambda: sa.Column("totp_failed_count", sa.Integer(), server_default="0", nullable=False),
    ),
    ("totp_locked_until", lambda: sa.Column("totp_locked_until", sa.DateTime(timezone=True), nullable=True)),
]

_SETTINGS_COLS = [
    (
        "totp_required",
        lambda: sa.Column("totp_required", sa.Boolean(), server_default="0", nullable=False),
    ),
    (
        "totp_required_changed_at",
        lambda: sa.Column("totp_required_changed_at", sa.DateTime(timezone=True), nullable=True),
    ),
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
    _add_missing("auth_settings", _SETTINGS_COLS)


def downgrade() -> None:
    _drop_existing("auth_settings", _SETTINGS_COLS)
    _drop_existing("users", _USER_COLS)
