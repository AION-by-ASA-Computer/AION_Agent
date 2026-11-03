"""Canale Telegram: tg_sessions (chat Telegram → conversazione AION corrente).

Revision ID: b0c1d2e030
Revises: t0g1l2k029
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e030"
down_revision: Union[str, None] = "t0g1l2k029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "tg_sessions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "tg_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "aion_user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("profile_slug", sa.String(128), nullable=True),
        sa.Column("project_slug", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "bot_id", "chat_id", "thread_id", "tg_user_id", name="uq_tg_sessions_key"
        ),
    )


def downgrade() -> None:
    if "tg_sessions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("tg_sessions")
