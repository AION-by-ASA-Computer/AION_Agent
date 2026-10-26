"""Policy nuovi account SSO: auth_settings.sso_signup_policy/sso_signup_allowlist.

Revision ID: z8a9b0c028
Revises: y7z8a9b027
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "z8a9b0c028"
down_revision: Union[str, None] = "y7z8a9b027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SETTINGS_COLS = [
    (
        "sso_signup_policy",
        lambda: sa.Column(
            "sso_signup_policy", sa.String(16), server_default="open", nullable=False
        ),
    ),
    (
        "sso_signup_allowlist",
        lambda: sa.Column("sso_signup_allowlist", sa.Text(), nullable=True),
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
    _add_missing("auth_settings", _SETTINGS_COLS)


def downgrade() -> None:
    _drop_existing("auth_settings", _SETTINGS_COLS)
