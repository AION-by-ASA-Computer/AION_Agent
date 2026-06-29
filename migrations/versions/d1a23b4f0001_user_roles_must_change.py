"""add users.roles + users.must_change_password

Revision ID: d1a23b4f0001
Revises: 8f9132ac41a1
Create Date: 2026-05-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1a23b4f0001"
down_revision: Union[str, None] = "8f9132ac41a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "users")
    if "roles" not in cols:
        op.add_column(
            "users",
            sa.Column("roles", sa.Text(), nullable=False, server_default="[]"),
        )
    if "must_change_password" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "roles")
