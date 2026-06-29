"""add todos column to execution plans

Revision ID: 8f9132ac41a1
Revises: c31b8f5d1f42
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f9132ac41a1"
down_revision: Union[str, None] = "c31b8f5d1f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("execution_plans")}
    if "todos" not in cols:
        op.add_column("execution_plans", sa.Column("todos", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("execution_plans", "todos")

