"""Canale Telegram: tg_links, tg_pairing_codes, tg_audit.

Tabelle del modulo src/channels/telegram (DeclarativeBase separato). FK verso
users.id con ON DELETE CASCADE: eliminando un utente spariscono collegamenti e
codici (create_table supporta le FK anche su SQLite, a differenza di ADD CONSTRAINT).

Revision ID: a9b0c1d029
Revises: z8a9b0c028
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b0c1d029"
down_revision: Union[str, None] = "z8a9b0c028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "tg_links" not in existing:
        op.create_table(
            "tg_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "aion_user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
            sa.Column("tg_username", sa.String(64), nullable=True),
            sa.Column("tg_first_name", sa.String(128), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("aion_user_id", name="uq_tg_links_aion_user_id"),
            sa.UniqueConstraint("tg_user_id", name="uq_tg_links_tg_user_id"),
        )
    if "tg_pairing_codes" not in existing:
        op.create_table(
            "tg_pairing_codes",
            sa.Column("code_hash", sa.String(64), primary_key=True),
            sa.Column(
                "aion_user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("used_by_tg_user_id", sa.BigInteger(), nullable=True),
        )
        op.create_index(
            "ix_tg_pairing_codes_aion_user_id", "tg_pairing_codes", ["aion_user_id"]
        )
    if "tg_audit" not in existing:
        op.create_table(
            "tg_audit",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "ts",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("actor_tg_user_id", sa.BigInteger(), nullable=True),
            sa.Column("aion_user_id", sa.String(64), nullable=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
        )
        op.create_index("ix_tg_audit_aion_user_id", "tg_audit", ["aion_user_id"])


def downgrade() -> None:
    existing = _tables()
    for table in ("tg_audit", "tg_pairing_codes", "tg_links"):
        if table in existing:
            op.drop_table(table)
