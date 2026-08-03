"""Mnemos LTM: projects rename, ltm_notes/digests, conversation.project_id

Revision ID: o7p8q9r017
Revises: n6o7p8q016
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o7p8q9r017"
down_revision: Union[str, None] = "n6o7p8q016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _column_nullable(bind, table: str, column: str) -> bool | None:
    for col in sa.inspect(bind).get_columns(table):
        if col["name"] == column:
            return bool(col.get("nullable"))
    return None


def _drop_stale_batch_tables(bind) -> None:
    for name in _table_names(bind):
        if name.startswith("_alembic_tmp_"):
            op.execute(f'DROP TABLE IF EXISTS "{name}"')


def _consolidate_projects_table(bind) -> None:
    """Move legacy sql_query_projects data into projects (bootstrap may create empty projects)."""
    names = _table_names(bind)
    if "sql_query_projects" not in names:
        return

    if "projects" in names:
        legacy_rows = bind.execute(
            sa.text("SELECT COUNT(*) FROM sql_query_projects")
        ).scalar_one()
        new_rows = bind.execute(sa.text("SELECT COUNT(*) FROM projects")).scalar_one()
        if legacy_rows and not new_rows:
            op.drop_table("projects")
        elif legacy_rows and new_rows:
            raise RuntimeError(
                "Both projects and sql_query_projects contain rows; "
                "manual merge required before migration o7p8q9r017"
            )

    names = _table_names(bind)
    if "sql_query_projects" in names and "projects" not in names:
        op.rename_table("sql_query_projects", "projects")


def upgrade() -> None:
    bind = op.get_bind()
    _drop_stale_batch_tables(bind)
    _consolidate_projects_table(bind)

    names = _table_names(bind)

    if "projects" in names:
        cols = _columns(bind, "projects")
        if "datasource_key" in cols and _column_nullable(bind, "projects", "datasource_key") is False:
            with op.batch_alter_table("projects") as batch_op:
                batch_op.alter_column(
                    "datasource_key",
                    existing_type=sa.String(length=128),
                    nullable=True,
                )

    if "conversations" in names:
        cols = _columns(bind, "conversations")
        if "project_id" not in cols and "projects" in names:
            project_id_col = sa.Column("project_id", sa.Integer(), nullable=True)
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("conversations") as batch_op:
                    batch_op.add_column(project_id_col)
                    batch_op.create_foreign_key(
                        "fk_conversations_project_id",
                        "projects",
                        ["project_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )
                    batch_op.create_index(
                        "ix_conversations_project_id",
                        ["project_id"],
                        unique=False,
                    )
            else:
                op.add_column("conversations", project_id_col)
                op.create_foreign_key(
                    "fk_conversations_project_id",
                    "conversations",
                    "projects",
                    ["project_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                op.create_index(
                    "ix_conversations_project_id",
                    "conversations",
                    ["project_id"],
                    unique=False,
                )

    if "ltm_notes" not in names:
        op.create_table(
            "ltm_notes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            ),
            sa.Column("scope_type", sa.String(length=16), nullable=False),
            sa.Column("scope_key", sa.String(length=256), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("content", sa.String(length=500), nullable=False),
            sa.Column(
                "category",
                sa.String(length=32),
                nullable=False,
                server_default="fact",
            ),
            sa.Column(
                "importance",
                sa.Integer(),
                nullable=False,
                server_default="3",
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
            sa.Column("superseded_by", sa.Integer(), nullable=True),
            sa.Column("source_session_id", sa.String(length=64), nullable=True),
            sa.Column("source_message_id", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["superseded_by"],
                ["ltm_notes.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "scope_type",
                "scope_key",
                "seq",
                name="uq_ltm_notes_scope_seq",
            ),
        )
        op.create_index(
            "ix_ltm_notes_scope",
            "ltm_notes",
            ["tenant_id", "scope_type", "scope_key", "seq"],
            unique=False,
        )
        op.create_index(
            "ix_ltm_notes_status",
            "ltm_notes",
            ["tenant_id", "scope_type", "scope_key", "status"],
            unique=False,
        )

    if "ltm_digests" not in names:
        op.create_table(
            "ltm_digests",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "tenant_id",
                sa.String(length=64),
                nullable=False,
                server_default="default",
            ),
            sa.Column("scope_type", sa.String(length=16), nullable=False),
            sa.Column("scope_key", sa.String(length=256), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False),
            sa.Column("range_start_seq", sa.Integer(), nullable=False),
            sa.Column("range_end_seq", sa.Integer(), nullable=False),
            sa.Column("summary_text", sa.String(length=500), nullable=True),
            sa.Column(
                "ready",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id",
                "scope_type",
                "scope_key",
                "range_start_seq",
                "range_end_seq",
                name="uq_ltm_digests_scope_range",
            ),
        )
        op.create_index(
            "ix_ltm_digests_scope_range",
            "ltm_digests",
            [
                "tenant_id",
                "scope_type",
                "scope_key",
                "range_start_seq",
                "range_end_seq",
            ],
            unique=False,
        )

    names = _table_names(bind)
    if "ltm_notes_fts" not in names and "ltm_notes" in names:
        op.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS ltm_notes_fts USING fts5(
                content,
                tenant_id UNINDEXED,
                scope_type UNINDEXED,
                scope_key UNINDEXED,
                note_id UNINDEXED,
                tokenize='unicode61'
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    names = _table_names(bind)

    if "ltm_notes_fts" in names:
        op.execute("DROP TABLE IF EXISTS ltm_notes_fts")

    if "ltm_digests" in names:
        op.drop_index("ix_ltm_digests_scope_range", table_name="ltm_digests")
        op.drop_table("ltm_digests")

    if "ltm_notes" in names:
        op.drop_index("ix_ltm_notes_status", table_name="ltm_notes")
        op.drop_index("ix_ltm_notes_scope", table_name="ltm_notes")
        op.drop_table("ltm_notes")

    if "conversations" in names:
        cols = _columns(bind, "conversations")
        if "project_id" in cols:
            op.drop_index("ix_conversations_project_id", table_name="conversations")
            op.drop_constraint("fk_conversations_project_id", "conversations", type_="foreignkey")
            op.drop_column("conversations", "project_id")

    if "projects" in names and "sql_query_projects" not in names:
        with op.batch_alter_table("projects") as batch_op:
            batch_op.alter_column(
                "datasource_key",
                existing_type=sa.String(length=128),
                nullable=False,
            )
        op.rename_table("projects", "sql_query_projects")
