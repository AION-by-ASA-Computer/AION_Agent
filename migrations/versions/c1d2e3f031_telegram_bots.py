"""Canale Telegram: tg_bots (bot personali creati dal manager) e tg_pending_creations.

Revision ID: c1d2e3f031
Revises: b0c1d2e030
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f031"
down_revision: Union[str, None] = "b0c1d2e030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "tg_bots" not in tables:
        op.create_table(
            "tg_bots",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "owner_aion_user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("owner_tg_user_id", sa.BigInteger(), nullable=False),
            sa.Column("bot_tg_id", sa.BigInteger(), nullable=False, unique=True),
            sa.Column("username", sa.String(64), nullable=True),
            sa.Column("name", sa.String(128), nullable=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("profile_slug", sa.String(128), nullable=True),
            sa.Column("project_slug", sa.String(128), nullable=True),
            sa.Column("token_enc", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_tg_bots_owner_aion_user_id", "tg_bots", ["owner_aion_user_id"]
        )
    if "tg_pending_creations" not in tables:
        op.create_table(
            "tg_pending_creations",
            sa.Column("owner_tg_user_id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "owner_aion_user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("request_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("profile_slug", sa.String(128), nullable=True),
            sa.Column("project_slug", sa.String(128), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "tg_pending_creations" in tables:
        op.drop_table("tg_pending_creations")
    if "tg_bots" in tables:
        op.drop_index("ix_tg_bots_owner_aion_user_id", table_name="tg_bots")
        op.drop_table("tg_bots")
