"""add messages.timeline_json for interleaved chat UI timeline

Revision ID: g3h4i5j6k007
Revises: a8c1d2e3f004
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g3h4i5j6k007"
down_revision: Union[str, None] = "a8c1d2e3f004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "messages")
    if "timeline_json" not in cols:
        op.add_column("messages", sa.Column("timeline_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "messages")
    if "timeline_json" in cols:
        op.drop_column("messages", "timeline_json")
