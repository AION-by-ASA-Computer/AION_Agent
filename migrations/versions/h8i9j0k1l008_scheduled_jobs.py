"""scheduled_jobs + scheduled_job_runs for per-user cron

Revision ID: h8i9j0k1l008
Revises: g3h4i5j6k007
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l008"
down_revision: Union[str, None] = "g3h4i5j6k007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())
    if "scheduled_jobs" not in names:
        op.create_table(
            "scheduled_jobs",
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False, server_default="default"),
            sa.Column("user_id", sa.String(length=256), nullable=False),
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("cron_expression", sa.String(length=128), nullable=False),
            sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
            sa.Column("profile_slug", sa.String(length=256), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("session_mode", sa.String(length=16), nullable=False, server_default="fixed"),
            sa.Column("session_id", sa.String(length=128), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("agent_mode", sa.String(length=32), nullable=False, server_default="normal"),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=32), nullable=False, server_default="user"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("job_id"),
        )
        op.create_index("ix_scheduled_jobs_user_id", "scheduled_jobs", ["user_id"], unique=False)
        op.create_index("ix_scheduled_jobs_tenant_id", "scheduled_jobs", ["tenant_id"], unique=False)
        op.create_index("ix_scheduled_jobs_enabled", "scheduled_jobs", ["enabled"], unique=False)
        op.create_index("ix_scheduled_jobs_next_run_at", "scheduled_jobs", ["next_run_at"], unique=False)
    if "scheduled_job_runs" not in names:
        op.create_table(
            "scheduled_job_runs",
            sa.Column("run_id", sa.String(length=64), nullable=False),
            sa.Column("job_id", sa.String(length=64), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("session_id", sa.String(length=128), nullable=True),
            sa.Column("conversation_id", sa.String(length=128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("assistant_preview", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["scheduled_jobs.job_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("run_id"),
        )
        op.create_index("ix_scheduled_job_runs_job_id", "scheduled_job_runs", ["job_id"], unique=False)
        op.create_index("ix_scheduled_job_runs_started_at", "scheduled_job_runs", ["started_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scheduled_job_runs_started_at", table_name="scheduled_job_runs")
    op.drop_index("ix_scheduled_job_runs_job_id", table_name="scheduled_job_runs")
    op.drop_table("scheduled_job_runs")
    op.drop_index("ix_scheduled_jobs_next_run_at", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_enabled", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_tenant_id", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_user_id", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
