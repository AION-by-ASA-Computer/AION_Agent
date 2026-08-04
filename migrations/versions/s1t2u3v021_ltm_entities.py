"""Add Mnemos entity mention index tables.

Revision ID: s1t2u3v021
Revises: r0s1t2u020
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s1t2u3v021"
down_revision: Union[str, None] = "r0s1t2u020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "ltm_entities" not in tables:
        op.create_table(
            "ltm_entities",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("scope_type", sa.String(16), nullable=False),
            sa.Column("scope_key", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False, server_default="generic"),
            sa.Column("canonical_key", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("aliases_json", sa.Text(), nullable=True),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
            sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(
            "ix_ltm_entities_scope_key",
            "ltm_entities",
            ["tenant_id", "scope_type", "scope_key", "canonical_key"],
            unique=True,
        )
    if "ltm_note_entities" not in tables:
        op.create_table(
            "ltm_note_entities",
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("ltm_notes.id"), primary_key=True),
            sa.Column("entity_id", sa.Integer(), sa.ForeignKey("ltm_entities.id"), primary_key=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "ltm_note_entities" in tables:
        op.drop_table("ltm_note_entities")
    if "ltm_entities" in tables:
        op.drop_index("ix_ltm_entities_scope_key", table_name="ltm_entities")
        op.drop_table("ltm_entities")
