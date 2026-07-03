"""add credential_mode and aion_connector_id to mcp_server_configs

Revision ID: f7a8b9c0d001
Revises: e5f12c3a0002
Create Date: 2026-05-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d001"
down_revision: Union[str, None] = "e5f12c3a0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "mcp_server_configs" not in sa.inspect(bind).get_table_names():
        return
    cols = _columns(bind, "mcp_server_configs")
    if "credential_mode" not in cols:
        op.add_column(
            "mcp_server_configs",
            sa.Column(
                "credential_mode",
                sa.String(32),
                nullable=False,
                server_default="none",
            ),
        )
    if "aion_connector_id" not in cols:
        op.add_column(
            "mcp_server_configs",
            sa.Column("aion_connector_id", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "mcp_server_configs" not in sa.inspect(bind).get_table_names():
        return
    cols = _columns(bind, "mcp_server_configs")
    if "aion_connector_id" in cols:
        op.drop_column("mcp_server_configs", "aion_connector_id")
    if "credential_mode" in cols:
        op.drop_column("mcp_server_configs", "credential_mode")
