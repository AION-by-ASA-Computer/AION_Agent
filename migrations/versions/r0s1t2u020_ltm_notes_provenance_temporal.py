"""Add provenance, confidence, and temporal columns to ltm_notes.

Revision ID: r0s1t2u020
Revises: q9r0s1t019
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r0s1t2u020"
down_revision: Union[str, None] = "q9r0s1t019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "ltm_notes" not in sa.inspect(bind).get_table_names():
        return
    cols = _cols(bind, "ltm_notes")
    with op.batch_alter_table("ltm_notes") as batch:
        if "confidence" not in cols:
            batch.add_column(
                sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0")
            )
        if "confidence_source" not in cols:
            batch.add_column(sa.Column("confidence_source", sa.String(24), nullable=True))
        if "valid_from" not in cols:
            batch.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        if "valid_to" not in cols:
            batch.add_column(sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True))
        if "last_recalled_at" not in cols:
            batch.add_column(
                sa.Column("last_recalled_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "recall_count" not in cols:
            batch.add_column(
                sa.Column("recall_count", sa.Integer(), nullable=False, server_default="0")
            )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ltm_notes_scope_status "
        "ON ltm_notes (tenant_id, scope_type, scope_key, status)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "ltm_notes" not in sa.inspect(bind).get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_ltm_notes_scope_status")
    cols = _cols(bind, "ltm_notes")
    with op.batch_alter_table("ltm_notes") as batch:
        for name in (
            "recall_count",
            "last_recalled_at",
            "valid_to",
            "valid_from",
            "confidence_source",
            "confidence",
        ):
            if name in cols:
                batch.drop_column(name)
