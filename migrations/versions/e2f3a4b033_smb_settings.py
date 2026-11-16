"""SMB file server settings per tenant (``smb_files`` MCP connector).

Revision ID: e2f3a4b033
Revises: d1e2f3a032

One row per tenant with host, allowed shares and limits, edited from
admin-ui (Settings -> File server) via ``/admin/smb``.  Holds no secrets.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f3a4b033"
down_revision: Union[str, None] = "d1e2f3a032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: the table may already exist when created by create_all at bootstrap.
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "smb_settings" in tables:
        return
    op.create_table(
        "smb_settings",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=True),
        sa.Column("host", sa.String(length=256), nullable=True),
        sa.Column("port", sa.Integer(), server_default="445", nullable=True),
        sa.Column("default_domain", sa.String(length=128), nullable=True),
        sa.Column("shares_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column(
            "auth_protocol", sa.String(length=16), server_default="ntlm", nullable=False
        ),
        sa.Column(
            "require_encryption", sa.Boolean(), server_default="0", nullable=True
        ),
        sa.Column("max_read_mb", sa.Integer(), server_default="25", nullable=True),
        sa.Column("max_write_mb", sa.Integer(), server_default="25", nullable=True),
        sa.Column("lockout_minutes", sa.Integer(), server_default="30", nullable=True),
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


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "smb_settings" in tables:
        op.drop_table("smb_settings")
