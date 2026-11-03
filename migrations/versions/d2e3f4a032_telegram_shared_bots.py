"""Canale Telegram: modalità dei bot (personale/condiviso) e registro dei gruppi.

Revision ID: d2e3f4a032
Revises: c1d2e3f031
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a032"
down_revision: Union[str, None] = "c1d2e3f031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODE_TABLES = ("tg_bots", "tg_pending_creations")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    for table in _MODE_TABLES:
        if table in tables and "mode" not in {
            c["name"] for c in insp.get_columns(table)
        }:
            op.add_column(
                table,
                sa.Column(
                    "mode", sa.String(16), nullable=False, server_default="personal"
                ),
            )
    if "tg_group_messages" not in tables:
        op.create_table(
            "tg_group_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("bot_id", sa.BigInteger(), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
            sa.Column("author", sa.String(128), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_tg_group_messages_chat",
            "tg_group_messages",
            ["bot_id", "chat_id", "id"],
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "tg_group_messages" in tables:
        op.drop_index("ix_tg_group_messages_chat", table_name="tg_group_messages")
        op.drop_table("tg_group_messages")
    for table in _MODE_TABLES:
        if table in tables and "mode" in {c["name"] for c in insp.get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.drop_column("mode")
