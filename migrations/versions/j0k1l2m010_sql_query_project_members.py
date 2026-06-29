"""SQL QueryMemory project members (shared access / invites)

Revision ID: j0k1l2m010
Revises: i9j0k1l009
Create Date: 2026-05-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0k1l2m010"
down_revision: Union[str, None] = "i9j0k1l009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "sql_query_project_members" in set(insp.get_table_names()):
        return
    op.create_table(
        "sql_query_project_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("user_identifier", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("invited_by", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["sql_query_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "user_identifier",
            name="uq_sql_query_project_member",
        ),
    )
    op.create_index(
        "ix_sql_query_project_members_user",
        "sql_query_project_members",
        ["user_identifier"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sql_query_project_members_user", table_name="sql_query_project_members")
    op.drop_table("sql_query_project_members")
