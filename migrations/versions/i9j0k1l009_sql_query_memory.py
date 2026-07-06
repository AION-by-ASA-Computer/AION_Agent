"""SQL QueryMemory: projects, cached_sql_queries, tenant settings

Revision ID: i9j0k1l009
Revises: h8i9j0k1l008
Create Date: 2026-05-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9j0k1l009"
down_revision: Union[str, None] = "h8i9j0k1l008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    names = set(insp.get_table_names())

    if "tenant_query_memory_settings" not in names:
        op.create_table(
            "tenant_query_memory_settings",
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column(
                "sql_default_scope",
                sa.String(length=16),
                nullable=False,
                server_default="per_user",
            ),
            sa.Column(
                "sql_auto_learn",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "sql_search_before_run",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("tenant_id"),
        )

    if "sql_query_projects" not in names:
        op.create_table(
            "sql_query_projects",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            ),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("display_name", sa.String(length=256), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "datasource_key",
                sa.String(length=128),
                nullable=False,
                server_default="default",
            ),
            sa.Column("profile_slug", sa.String(length=256), nullable=True),
            sa.Column(
                "scope_mode",
                sa.String(length=16),
                nullable=False,
                server_default="inherit",
            ),
            sa.Column("created_by", sa.String(length=256), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "slug", name="uq_sql_query_project_tenant_slug"
            ),
        )
        op.create_index(
            "ix_sql_query_projects_tenant",
            "sql_query_projects",
            ["tenant_id"],
            unique=False,
        )

    if "cached_sql_queries" not in names:
        op.create_table(
            "cached_sql_queries",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            ),
            sa.Column("user_id", sa.String(length=256), nullable=True),
            sa.Column("user_scope_key", sa.String(length=256), nullable=False),
            sa.Column("user_request", sa.Text(), nullable=False),
            sa.Column("sql_text", sa.Text(), nullable=False),
            sa.Column("sql_fingerprint", sa.String(length=64), nullable=False),
            sa.Column("embedding_request", sa.LargeBinary(), nullable=True),
            sa.Column("embedding_sql", sa.LargeBinary(), nullable=True),
            sa.Column("tables_used_json", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("is_verified", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "success_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "failure_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["project_id"], ["sql_query_projects.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "user_scope_key",
                "sql_fingerprint",
                name="uq_cached_sql_project_scope_fp",
            ),
        )
        op.create_index(
            "ix_cached_sql_queries_project",
            "cached_sql_queries",
            ["project_id"],
            unique=False,
        )
        op.create_index(
            "ix_cached_sql_queries_tenant_user",
            "cached_sql_queries",
            ["tenant_id", "user_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_cached_sql_queries_tenant_user", table_name="cached_sql_queries")
    op.drop_index("ix_cached_sql_queries_project", table_name="cached_sql_queries")
    op.drop_table("cached_sql_queries")
    op.drop_index("ix_sql_query_projects_tenant", table_name="sql_query_projects")
    op.drop_table("sql_query_projects")
    op.drop_table("tenant_query_memory_settings")
