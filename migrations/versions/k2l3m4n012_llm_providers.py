"""add llm_providers table

Revision ID: k2l3m4n012
Revises: k1l2m3n011
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = "k2l3m4n012"
down_revision = "k1l2m3n011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("icon_url", sa.String(512)),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(256), nullable=False),
        sa.Column("api_base_url", sa.String(1024)),
        sa.Column("api_key_encrypted", sa.Text()),
        sa.Column("timeout", sa.Integer, server_default="120"),
        sa.Column("max_chat_tokens", sa.Integer),
        sa.Column("thinking_token_budget", sa.Integer),
        sa.Column("enabled", sa.Boolean, server_default="1", nullable=False),
        sa.Column("is_default", sa.Boolean, server_default="0", nullable=False),
        sa.Column("metadata", sa.Text(), server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_llm_provider_tenant_slug"),
    )


def downgrade() -> None:
    op.drop_table("llm_providers")
