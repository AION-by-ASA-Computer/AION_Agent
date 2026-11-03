"""WhatsApp channel: whatsapp_identities.pending_attachments_json.

Media sent without a caption are saved in the conversation and parked here
(JSON list of AttachmentRef dicts) until the user's next text message, which
runs the agent turn with them attached. Idempotent: skips when the table or
column already exists (e.g. DB created with ``create_all`` from the model).

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

_TABLE = "whatsapp_identities"
_COLUMN = "pending_attachments_json"


def _existing_columns() -> set:
    """Column names of the table, empty when the table does not exist yet."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    cols = _existing_columns()
    if cols and _COLUMN not in cols:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    if _COLUMN in _existing_columns():
        # batch_alter_table: SQLite does not support DROP COLUMN on every version.
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
