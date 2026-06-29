"""execution_plans + orchestration_audit

Revision ID: b2c9e8add_orch
Revises: 15a42b5aff9f
Create Date: 2026-05-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c9e8add_orch"
down_revision: Union[str, None] = "15a42b5aff9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = insp.get_table_names()
    if "execution_plans" not in names:
        op.create_table(
            "execution_plans",
            sa.Column("plan_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("user_id", sa.String(length=256), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("draft_json", sa.Text(), nullable=False),
            sa.Column("approved_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("audit_meta", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("plan_id"),
        )
        op.create_index(op.f("ix_execution_plans_session_id"), "execution_plans", ["session_id"], unique=False)
        op.create_index(op.f("ix_execution_plans_status"), "execution_plans", ["status"], unique=False)
    if "orchestration_audit" not in names:
        op.create_table(
            "orchestration_audit",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("plan_id", sa.String(length=64), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=False),
            sa.Column("actor", sa.String(length=256), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_orchestration_audit_plan_id"), "orchestration_audit", ["plan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_orchestration_audit_plan_id"), table_name="orchestration_audit")
    op.drop_table("orchestration_audit")
    op.drop_index(op.f("ix_execution_plans_status"), table_name="execution_plans")
    op.drop_index(op.f("ix_execution_plans_session_id"), table_name="execution_plans")
    op.drop_table("execution_plans")
