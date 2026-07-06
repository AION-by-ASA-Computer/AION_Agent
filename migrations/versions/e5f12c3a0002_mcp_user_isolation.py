"""mcp_user_isolation: add mcp_server_configs and user_mcp_credentials

Revision ID: e5f12c3a0002
Revises: d1a23b4f0001
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f12c3a0002"
down_revision: Union[str, None] = "d1a23b4f0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()

    if "mcp_server_configs" not in tables:
        op.create_table(
            "mcp_server_configs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("server_slug", sa.String(128), nullable=False, unique=True),
            sa.Column("display_name", sa.String(256), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("icon_url", sa.String(512)),
            sa.Column(
                "is_enabled_for_users",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "requires_user_credentials",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("credential_schema", sa.Text()),
            sa.Column("oauth_config", sa.Text()),
            sa.Column("category", sa.String(64)),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )

    if "user_mcp_credentials" not in tables:
        op.create_table(
            "user_mcp_credentials",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.String(256), nullable=False),
            sa.Column(
                "tenant_id", sa.String(64), nullable=False, server_default="default"
            ),
            sa.Column("server_slug", sa.String(128), nullable=False),
            sa.Column("credential_key", sa.String(128), nullable=False),
            sa.Column("value_encrypted", sa.Text(), nullable=False),
            sa.Column("display_hint", sa.String(128)),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
            ),
        )
        op.create_index(
            "ix_user_mcp_credentials_user_id", "user_mcp_credentials", ["user_id"]
        )
        op.create_unique_constraint(
            "uq_user_mcp_credential",
            "user_mcp_credentials",
            ["user_id", "tenant_id", "server_slug", "credential_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = insp.get_table_names()
    if "user_mcp_credentials" in tables:
        op.drop_table("user_mcp_credentials")
    if "mcp_server_configs" in tables:
        op.drop_table("mcp_server_configs")
