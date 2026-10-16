"""SSO implementation models.

Revision ID: t2u3v4w022
Revises: s1t2u3v021
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "t2u3v4w022"
down_revision: Union[str, None] = "s1t2u3v021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    
    if "sso_providers" not in tables:
        op.create_table(
            "sso_providers",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("client_id", sa.String(length=256), nullable=False),
            sa.Column("client_secret_encrypted", sa.Text(), nullable=True),
            sa.Column("directory_tenant_id", sa.String(length=64), nullable=True),
            sa.Column("allowed_domains", sa.Text(), nullable=True),
            sa.Column("auto_provision", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("default_roles", sa.Text(), server_default='["user"]', nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
            sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("validated_by_user_id", sa.String(length=64), nullable=True),
            sa.Column("client_secret_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
            sa.ForeignKeyConstraint(['validated_by_user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('tenant_id', 'provider', name='uq_sso_providers_tenant_provider')
        )
        
    if "user_sso_identities" not in tables:
        op.create_table(
            "user_sso_identities",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("subject", sa.String(length=256), nullable=False),
            sa.Column("email", sa.String(length=256), nullable=True),
            sa.Column("display_name", sa.String(length=256), nullable=True),
            sa.Column("access_token_encrypted", sa.Text(), nullable=True),
            sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('tenant_id', 'provider', 'subject', name='uq_user_sso_identities_provider_subject')
        )
        op.create_index('ix_user_sso_identities_user_id', 'user_sso_identities', ['user_id'], unique=False)
        
    if "sso_auth_states" not in tables:
        op.create_table(
            "sso_auth_states",
            sa.Column("state_hash", sa.String(length=64), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("purpose", sa.String(length=32), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("nonce", sa.String(length=64), nullable=True),
            sa.Column("code_verifier_encrypted", sa.Text(), nullable=True),
            sa.Column("user_id", sa.String(length=64), nullable=True),
            sa.Column("return_to", sa.String(length=2048), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('state_hash')
        )

    try:
        op.create_index('ix_users_email_lower', 'users', [sa.text('lower(email)')], unique=False)
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index('ix_users_email_lower', table_name='users')
    except Exception:
        pass
    
    op.drop_table("sso_auth_states")
    op.drop_index('ix_user_sso_identities_user_id', table_name='user_sso_identities')
    op.drop_table("user_sso_identities")
    op.drop_table("sso_providers")
