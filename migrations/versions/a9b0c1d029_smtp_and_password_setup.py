"""SMTP settings + link monouso per impostare la password.

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


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "smtp_settings" not in tables:
        op.create_table(
            "smtp_settings",
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="1", nullable=True),
            sa.Column("host", sa.String(length=256), nullable=True),
            sa.Column("port", sa.Integer(), server_default="587", nullable=True),
            sa.Column(
                "security",
                sa.String(length=16),
                server_default="starttls",
                nullable=False,
            ),
            sa.Column("username", sa.String(length=256), nullable=True),
            sa.Column("password_encrypted", sa.Text(), nullable=True),
            sa.Column("from_address", sa.String(length=256), nullable=True),
            sa.Column("from_name", sa.String(length=256), nullable=True),
            sa.Column("reply_to", sa.String(length=256), nullable=True),
            sa.Column(
                "email_language",
                sa.String(length=8),
                server_default="it",
                nullable=False,
            ),
            sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_test_ok", sa.Boolean(), nullable=True),
            sa.Column("last_test_error", sa.String(length=64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("tenant_id"),
        )

    if "password_setup_tokens" not in tables:
        op.create_table(
            "password_setup_tokens",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("purpose", sa.String(length=16), nullable=False),
            sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("send_error", sa.String(length=64), nullable=True),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_password_setup_tokens_user_id", "password_setup_tokens", ["user_id"]
        )
    else:
        # Tabella gia' creata da create_all con un modello precedente.
        cols = {
            c["name"]
            for c in sa.inspect(op.get_bind()).get_columns("password_setup_tokens")
        }
        if "sent_at" not in cols:
            op.add_column(
                "password_setup_tokens",
                sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            )
        if "send_error" not in cols:
            op.add_column(
                "password_setup_tokens",
                sa.Column("send_error", sa.String(length=64), nullable=True),
            )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "password_setup_tokens" in tables:
        op.drop_index(
            "ix_password_setup_tokens_user_id", table_name="password_setup_tokens"
        )
        op.drop_table("password_setup_tokens")
    if "smtp_settings" in tables:
        op.drop_table("smtp_settings")
