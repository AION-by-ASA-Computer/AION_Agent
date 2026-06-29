"""user_mcp_preferences and user_may_disable on mcp_server_configs

Revision ID: a8c1d2e3f004
Revises: f7a8b9c0d001
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c1d2e3f004"
down_revision: Union[str, None] = "f7a8b9c0d001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "mcp_server_configs" in tables:
        cols = _columns(bind, "mcp_server_configs")
        if "user_may_disable" not in cols:
            op.add_column(
                "mcp_server_configs",
                sa.Column("user_may_disable", sa.Boolean(), nullable=False, server_default=sa.true()),
            )
    if "user_mcp_preferences" not in tables:
        op.create_table(
            "user_mcp_preferences",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(256), nullable=False, index=True),
            sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
            sa.Column("server_slug", sa.String(128), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint(
                "user_id",
                "tenant_id",
                "server_slug",
                name="uq_user_mcp_preference",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "user_mcp_preferences" in tables:
        op.drop_table("user_mcp_preferences")
    if "mcp_server_configs" in tables:
        cols = _columns(bind, "mcp_server_configs")
        if "user_may_disable" in cols:
            op.drop_column("mcp_server_configs", "user_may_disable")
