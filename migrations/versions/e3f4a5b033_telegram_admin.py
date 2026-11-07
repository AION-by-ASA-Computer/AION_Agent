"""Canale Telegram: amministrazione (nuovo proprietario in attesa, ultima attività, quote).

Revision ID: e3f4a5b033
Revises: d2e3f4a032
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b033"
down_revision: Union[str, None] = "d2e3f4a032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BOT_COLUMNS = (
    ("pending_owner_tg_user_id", sa.BigInteger()),
    ("last_activity_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "tg_bots" in tables:
        existing = {c["name"] for c in insp.get_columns("tg_bots")}
        for name, type_ in _BOT_COLUMNS:
            if name not in existing:
                op.add_column("tg_bots", sa.Column(name, type_, nullable=True))
    if "tg_user_quotas" not in tables:
        op.create_table(
            "tg_user_quotas",
            sa.Column(
                "aion_user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("max_bots", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "tg_user_quotas" in tables:
        op.drop_table("tg_user_quotas")
    if "tg_bots" in tables:
        existing = {c["name"] for c in insp.get_columns("tg_bots")}
        with op.batch_alter_table("tg_bots") as batch:
            for name, _ in _BOT_COLUMNS:
                if name in existing:
                    batch.drop_column(name)
