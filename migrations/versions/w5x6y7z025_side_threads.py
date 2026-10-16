"""Side threads: conversations.parent_conversation_id / parent_message_id / anchor_json.

Revision ID: w5x6y7z025
Revises: v4w5x6y024
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w5x6y7z025"
down_revision: Union[str, None] = "v4w5x6y024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "conversations"
_INDEX = "ix_conversations_parent_conversation_id"

_COLS = [
    ("parent_conversation_id", lambda: sa.Column("parent_conversation_id", sa.String(64), nullable=True)),
    ("parent_message_id", lambda: sa.Column("parent_message_id", sa.String(64), nullable=True)),
    (
        "anchor_json",
        lambda: sa.Column("anchor_json", sa.Text(), server_default="{}", nullable=False),
    ),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, factory in _COLS:
        if name not in existing:
            op.add_column(_TABLE, factory())
    indexes = {i["name"] for i in inspector.get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(_INDEX, _TABLE, ["parent_conversation_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    to_drop = [n for n, _ in _COLS if n in existing]
    if not to_drop:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for n in to_drop:
            batch.drop_column(n)
