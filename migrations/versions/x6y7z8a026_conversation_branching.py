"""Conversation branching: root_conversation_id / forked_from_id / forked_at_message_id / fork_seq.

Revision ID: x6y7z8a026
Revises: w5x6y7z025
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "x6y7z8a026"
down_revision: Union[str, None] = "w5x6y7z025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONV_TABLE = "conversations"
_CONV_COLS = [
    ("root_conversation_id", lambda: sa.Column("root_conversation_id", sa.String(64), nullable=True)),
    ("forked_from_id", lambda: sa.Column("forked_from_id", sa.String(64), nullable=True)),
    ("forked_at_message_id", lambda: sa.Column("forked_at_message_id", sa.String(64), nullable=True)),
    ("fork_seq", lambda: sa.Column("fork_seq", sa.Integer(), nullable=True)),
]

_MSG_TABLE = "messages"
_MSG_COLS = [
    ("forked_from_message_id", lambda: sa.Column("forked_from_message_id", sa.String(64), nullable=True)),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if _CONV_TABLE in tables:
        existing = {c["name"] for c in inspector.get_columns(_CONV_TABLE)}
        for name, factory in _CONV_COLS:
            if name not in existing:
                op.add_column(_CONV_TABLE, factory())
        indexes = {i["name"] for i in inspector.get_indexes(_CONV_TABLE)}
        if "ix_conversations_root_conversation_id" not in indexes:
            op.create_index("ix_conversations_root_conversation_id", _CONV_TABLE, ["root_conversation_id"])
        if "ix_conversations_forked_from_id" not in indexes:
            op.create_index("ix_conversations_forked_from_id", _CONV_TABLE, ["forked_from_id"])

    if _MSG_TABLE in tables:
        existing_msg = {c["name"] for c in inspector.get_columns(_MSG_TABLE)}
        for name, factory in _MSG_COLS:
            if name not in existing_msg:
                op.add_column(_MSG_TABLE, factory())
        indexes_msg = {i["name"] for i in inspector.get_indexes(_MSG_TABLE)}
        if "idx_messages_forked_from" not in indexes_msg:
            op.create_index("idx_messages_forked_from", _MSG_TABLE, ["forked_from_message_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()

    if _CONV_TABLE in tables:
        indexes = {i["name"] for i in inspector.get_indexes(_CONV_TABLE)}
        for idx in ("ix_conversations_root_conversation_id", "ix_conversations_forked_from_id"):
            if idx in indexes:
                op.drop_index(idx, table_name=_CONV_TABLE)
        existing = {c["name"] for c in inspector.get_columns(_CONV_TABLE)}
        to_drop = [n for n, _ in _CONV_COLS if n in existing]
        if to_drop:
            with op.batch_alter_table(_CONV_TABLE) as batch:
                for n in to_drop:
                    batch.drop_column(n)

    if _MSG_TABLE in tables:
        indexes_msg = {i["name"] for i in inspector.get_indexes(_MSG_TABLE)}
        if "idx_messages_forked_from" in indexes_msg:
            op.drop_index("idx_messages_forked_from", table_name=_MSG_TABLE)
        existing_msg = {c["name"] for c in inspector.get_columns(_MSG_TABLE)}
        to_drop_msg = [n for n, _ in _MSG_COLS if n in existing_msg]
        if to_drop_msg:
            with op.batch_alter_table(_MSG_TABLE) as batch:
                for n in to_drop_msg:
                    batch.drop_column(n)
