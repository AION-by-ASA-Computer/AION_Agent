"""Canale WhatsApp (Cloud API): whatsapp_channels, whatsapp_identities,
whatsapp_link_codes, whatsapp_messages.

Revision ID: a9b0c1d029w
Revises: a9b0c1d029

Originally ``a9b0c1d029`` revising ``z8a9b0c028``; renamed when merging main,
which had already taken ``a9b0c1d029`` for the SMTP / password-setup migration.
The WhatsApp chain now runs after it so the history stays linear.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b0c1d029w"
down_revision: Union[str, None] = "a9b0c1d029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name: str, nullable: bool = True, now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if now else None,
    )


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "whatsapp_channels" not in tables:
        op.create_table(
            "whatsapp_channels",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column(
                "tenant_id",
                sa.String(64),
                sa.ForeignKey("tenants.id"),
                nullable=False,
                unique=True,
            ),
            sa.Column("enabled", sa.Boolean(), server_default="0"),
            sa.Column("waba_id", sa.String(64), nullable=True),
            sa.Column("phone_number_id", sa.String(64), nullable=True),
            sa.Column("display_phone_number", sa.String(32), nullable=True),
            sa.Column("verified_name", sa.String(256), nullable=True),
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
            sa.Column("app_secret_encrypted", sa.Text(), nullable=True),
            sa.Column("verify_token_encrypted", sa.Text(), nullable=True),
            sa.Column("default_profile_slug", sa.String(128), nullable=True),
            _ts("validated_at"),
            sa.Column(
                "validated_by_user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            _ts("webhook_verified_at"),
            _ts("last_webhook_at"),
            sa.Column("last_error", sa.Text(), nullable=True),
            _ts("created_at", now=True),
            _ts("updated_at", now=True),
        )
        op.create_index(
            "ix_whatsapp_channels_phone_number_id",
            "whatsapp_channels",
            ["phone_number_id"],
        )

    if "whatsapp_identities" not in tables:
        op.create_table(
            "whatsapp_identities",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("bsuid", sa.String(128), nullable=False),
            sa.Column("phone_e164", sa.String(32), nullable=True),
            sa.Column("wa_profile_name", sa.String(256), nullable=True),
            sa.Column(
                "user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("active_conversation_id", sa.String(64), nullable=True),
            _ts("linked_at", now=True),
            _ts("last_inbound_at"),
            sa.UniqueConstraint(
                "tenant_id", "bsuid", name="uq_whatsapp_identities_bsuid"
            ),
            sa.UniqueConstraint(
                "tenant_id", "user_id", name="uq_whatsapp_identities_user"
            ),
        )
        op.create_index(
            "ix_whatsapp_identities_user_id", "whatsapp_identities", ["user_id"]
        )

    if "whatsapp_link_codes" not in tables:
        op.create_table(
            "whatsapp_link_codes",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column(
                "user_id",
                sa.String(64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code_hash", sa.String(64), nullable=False),
            _ts("expires_at", nullable=False),
            _ts("used_at"),
            _ts("created_at", now=True),
        )
        op.create_index(
            "ix_whatsapp_link_codes_user_id", "whatsapp_link_codes", ["user_id"]
        )
        op.create_index(
            "ix_whatsapp_link_codes_code_hash", "whatsapp_link_codes", ["code_hash"]
        )

    if "whatsapp_messages" not in tables:
        op.create_table(
            "whatsapp_messages",
            sa.Column("wamid", sa.String(256), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("direction", sa.String(8), nullable=False),
            sa.Column("bsuid", sa.String(128), nullable=True),
            sa.Column("conversation_id", sa.String(64), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("error_code", sa.String(32), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            _ts("created_at", now=True),
            _ts("updated_at", now=True),
        )
        op.create_index(
            "ix_whatsapp_messages_status",
            "whatsapp_messages",
            ["direction", "status"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (
        "whatsapp_messages",
        "whatsapp_link_codes",
        "whatsapp_identities",
        "whatsapp_channels",
    ):
        if name in tables:
            op.drop_table(name)
