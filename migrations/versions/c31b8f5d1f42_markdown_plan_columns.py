"""add markdown columns for execution plans

Revision ID: c31b8f5d1f42
Revises: b2c9e8add_orch
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c31b8f5d1f42"
down_revision: Union[str, None] = "b2c9e8add_orch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _column_names(bind, "execution_plans")
    if "draft_markdown" not in cols:
        op.add_column("execution_plans", sa.Column("draft_markdown", sa.Text(), nullable=True))
    if "approved_markdown" not in cols:
        op.add_column("execution_plans", sa.Column("approved_markdown", sa.Text(), nullable=True))
    if "annotations" not in cols:
        op.add_column("execution_plans", sa.Column("annotations", sa.Text(), nullable=True))
    if "revision" not in cols:
        op.add_column("execution_plans", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        op.alter_column("execution_plans", "revision", server_default=None)


def downgrade() -> None:
    op.drop_column("execution_plans", "revision")
    op.drop_column("execution_plans", "annotations")
    op.drop_column("execution_plans", "approved_markdown")
    op.drop_column("execution_plans", "draft_markdown")

