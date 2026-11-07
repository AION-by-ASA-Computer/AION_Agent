"""Telegram channel: configuration stored encrypted in the DB (``tg_settings``).

The ``AION_TELEGRAM_*`` env variables are no longer read: Admin → Telegram writes
the whole channel configuration here (encrypted JSON, one row per tenant) and the
gateway applies it without restarting AION. New DBs get the table from
``src.channels.telegram.models.ensure_schema``; this migration covers existing
installations. Idempotent like the other Telegram migrations.

Revision ID: f4a5b6c034
Revises: e3f4a5b033
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a5b6c034"
down_revision: Union[str, None] = "e3f4a5b033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``tg_settings`` unless ``ensure_schema`` already did."""
    insp = sa.inspect(op.get_bind())
    if "tg_settings" in set(insp.get_table_names()):
        return
    op.create_table(
        "tg_settings",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("data_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "updated_by_user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "tg_settings" in set(insp.get_table_names()):
        op.drop_table("tg_settings")
