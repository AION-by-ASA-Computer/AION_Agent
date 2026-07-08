"""scheduled_jobs.sql_query_project column

Revision ID: m4n5o6p014
Revises: l3m4n5o013
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m4n5o6p014"
down_revision: Union[str, None] = "l3m4n5o013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())
    if "scheduled_jobs" in names:
        cols = {c["name"] for c in insp.get_columns("scheduled_jobs")}
        if "sql_query_project" not in cols:
            op.add_column(
                "scheduled_jobs",
                sa.Column("sql_query_project", sa.String(length=128), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())
    if "scheduled_jobs" in names:
        cols = {c["name"] for c in insp.get_columns("scheduled_jobs")}
        if "sql_query_project" in cols:
            op.drop_column("scheduled_jobs", "sql_query_project")
