"""user_profile_access table

Revision ID: l3m4n5o013
Revises: k2l3m4n012
Create Date: 2026-07-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l3m4n5o013"
down_revision: Union[str, None] = "k2l3m4n012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profile_access",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column(
            "user_id",
            sa.String(256),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("profile_slug", sa.String(256), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            "profile_slug",
            name="uq_user_profile_access",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_profile_access")
