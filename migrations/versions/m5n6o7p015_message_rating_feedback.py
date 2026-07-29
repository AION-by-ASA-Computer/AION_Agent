"""message rating and feedback comment columns

Revision ID: m5n6o7p015
Revises: m4n5o6p014
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m5n6o7p015"
down_revision: Union[str, None] = "m4n5o6p014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())
    if "messages" in names:
        cols = {c["name"] for c in insp.get_columns("messages")}
        if "rating" not in cols:
            op.add_column(
                "messages",
                sa.Column("rating", sa.Integer(), nullable=True),
            )
        if "feedback_comment" not in cols:
            op.add_column(
                "messages",
                sa.Column("feedback_comment", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())
    if "messages" in names:
        cols = {c["name"] for c in insp.get_columns("messages")}
        if "rating" in cols:
            op.drop_column("messages", "rating")
        if "feedback_comment" in cols:
            op.drop_column("messages", "feedback_comment")
