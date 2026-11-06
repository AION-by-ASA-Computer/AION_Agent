"""Session charts persisted in SQLite (``session_charts``).

Charts produced by the ``charts`` MCP tools used to live only in a Redis /
in-memory queue that chat-ui flushed at the end of the turn, so they vanished on
reload or chat switch. Rows are now copied here at the end of each SSE turn and
rendered inline in the assistant timeline. New DBs get the table from
``Base.metadata.create_all``; this migration covers existing installations and
is idempotent like the other recent migrations.

Revision ID: c4a7r8t035
Revises: f4a5b6c034
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4a7r8t035"
down_revision: Union[str, None] = "f4a5b6c034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``session_charts`` unless ``create_all`` already did."""
    insp = sa.inspect(op.get_bind())
    if "session_charts" in set(insp.get_table_names()):
        return
    op.create_table(
        "session_charts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("message_id", sa.String(64), nullable=True),
        sa.Column("tool_call_id", sa.String(128), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_session_charts_conversation_id", "session_charts", ["conversation_id"]
    )
    op.create_index("ix_session_charts_message_id", "session_charts", ["message_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "session_charts" in set(insp.get_table_names()):
        op.drop_table("session_charts")
