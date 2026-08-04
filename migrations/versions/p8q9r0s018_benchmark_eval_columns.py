"""Extend eval_runs for benchmark harness subprocess tracking.

Revision ID: p8q9r0s018
Revises: o7p8q9r017
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p8q9r0s018"
down_revision: Union[str, None] = "o7p8q9r017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "eval_runs" not in sa.inspect(bind).get_table_names():
        return
    cols = _cols(bind, "eval_runs")
    with op.batch_alter_table("eval_runs") as batch:
        if "benchmark_id" not in cols:
            batch.add_column(sa.Column("benchmark_id", sa.String(64), nullable=True))
        if "status" not in cols:
            batch.add_column(
                sa.Column("status", sa.String(32), nullable=True, server_default="pending")
            )
        if "config_json" not in cols:
            batch.add_column(sa.Column("config_json", sa.Text(), nullable=True))
        if "metrics_json" not in cols:
            batch.add_column(sa.Column("metrics_json", sa.Text(), nullable=True))
        if "log_path" not in cols:
            batch.add_column(sa.Column("log_path", sa.Text(), nullable=True))
        if "pid" not in cols:
            batch.add_column(sa.Column("pid", sa.Integer(), nullable=True))
        if "started_at" not in cols:
            batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        if "finished_at" not in cols:
            batch.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "eval_runs" not in sa.inspect(bind).get_table_names():
        return
    cols = _cols(bind, "eval_runs")
    with op.batch_alter_table("eval_runs") as batch:
        for name in (
            "finished_at",
            "started_at",
            "pid",
            "log_path",
            "metrics_json",
            "config_json",
            "status",
            "benchmark_id",
        ):
            if name in cols:
                batch.drop_column(name)
