"""add messages.metadata_json for plan execution task tags

Revision ID: k1l2m3n011
Revises: j0k1l2m010
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1l2m3n011"
down_revision: Union[str, None] = "j0k1l2m010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "messages")
    if "metadata_json" not in cols:
        op.add_column("messages", sa.Column("metadata_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "messages")
    if "metadata_json" in cols:
        op.drop_column("messages", "metadata_json")
