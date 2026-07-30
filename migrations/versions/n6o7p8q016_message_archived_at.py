"""message archived_at for non-destructive compaction

Revision ID: n6o7p8q016
Revises: m5n6o7p015
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n6o7p8q016"
down_revision: Union[str, None] = "m5n6o7p015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "messages" not in sa.inspect(bind).get_table_names():
        return
    cols = _columns(bind, "messages")
    if "archived_at" not in cols:
        op.add_column(
            "messages",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "archived_reason" not in cols:
        op.add_column(
            "messages",
            sa.Column("archived_reason", sa.String(32), nullable=True),
        )
    try:
        op.create_index(
            "ix_messages_conversation_archived",
            "messages",
            ["conversation_id", "archived_at"],
        )
    except Exception:
        pass


def downgrade() -> None:
    bind = op.get_bind()
    if "messages" not in sa.inspect(bind).get_table_names():
        return
    try:
        op.drop_index("ix_messages_conversation_archived", table_name="messages")
    except Exception:
        pass
    cols = _columns(bind, "messages")
    if "archived_reason" in cols:
        op.drop_column("messages", "archived_reason")
    if "archived_at" in cols:
        op.drop_column("messages", "archived_at")
