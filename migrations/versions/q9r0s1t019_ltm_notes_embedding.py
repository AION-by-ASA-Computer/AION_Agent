"""Add optional embedding column to ltm_notes for hybrid recall.

Revision ID: q9r0s1t019
Revises: p8q9r0s018
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q9r0s1t019"
down_revision: Union[str, None] = "p8q9r0s018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "ltm_notes" not in sa.inspect(bind).get_table_names():
        return
    cols = _cols(bind, "ltm_notes")
    if "embedding" not in cols:
        with op.batch_alter_table("ltm_notes") as batch:
            batch.add_column(sa.Column("embedding", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "ltm_notes" not in sa.inspect(bind).get_table_names():
        return
    cols = _cols(bind, "ltm_notes")
    if "embedding" in cols:
        with op.batch_alter_table("ltm_notes") as batch:
            batch.drop_column("embedding")
