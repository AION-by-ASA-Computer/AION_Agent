"""Local accounts under SSO: ``users.local_account``.

An admin can create a username+password account on purpose while an SSO login
mode is active (third parties who cannot use the company IdP). The flag unlocks
password login for those users only; they are also marked
``sso_migration_exempt`` by the API so the SSO migration ignores them.

Existing rows become ``false`` through the server default. Idempotent like the
other user-column migrations, because ``ensure_bootstrap_schema`` may already
have added the column on SQLite (see ``src/data/bootstrap.py``).

This revision also acts as a merge point: ``f3a4b5c034`` (smb_servers) was left
as a second, unmerged head on ``main``, which makes ``alembic upgrade head``
(used by ``src/data/migrations.py``) fail with "Multiple heads". Declaring both
parents restores a single head; the merge itself changes no schema.

Revision ID: i7l8c9a037
Revises: h6m7r8g036, f3a4b5c034
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i7l8c9a037"
down_revision: Union[str, Sequence[str], None] = ("h6m7r8g036", "f3a4b5c034")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ``users.local_account`` unless bootstrap already created it."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("users"):
        return
    existing = {c["name"] for c in inspector.get_columns("users")}
    if "local_account" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "local_account",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    """Drop the column (batch mode for SQLite)."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("users"):
        return
    existing = {c["name"] for c in inspector.get_columns("users")}
    if "local_account" in existing:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("local_account")
