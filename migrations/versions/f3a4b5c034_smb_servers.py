"""Multiple Windows file servers per tenant (``smb_files`` MCP connector).

Revision ID: f3a4b5c034
Revises: e2f3a4b033

Moves the per-server fields (host, port, domain, shares, protocol,
encryption, last test) out of ``smb_settings`` into the new ``smb_servers``
table, so the admin can configure several servers; ``smb_settings`` keeps
only the global switch and limits.  An existing single-server row becomes
the first server (credential set ``DEFAULT``, i.e. the user's existing
``SMB_USERNAME``/``SMB_PASSWORD``).  Holds no secrets.

Every step is idempotent because ``Base.metadata.create_all`` may already
have created ``smb_servers`` (and a fresh ``smb_settings``) at bootstrap.
"""

import re
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a4b5c034"
down_revision: Union[str, None] = "e2f3a4b033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Columns that move from smb_settings to smb_servers.
_MOVED = (
    "host",
    "port",
    "default_domain",
    "shares_json",
    "auth_protocol",
    "require_encryption",
    "last_test_at",
    "last_test_ok",
    "last_test_error",
)


def _alias_from_host(host: str) -> str:
    """First DNS label, sanitised to the alias format (``fs01`` fallback)."""
    first = (host or "").strip().lower().split(".")[0]
    alias = re.sub(r"[^a-z0-9-]", "-", first).strip("-")[:31]
    return alias if alias and alias[0].isalnum() else "fs01"


def _columns(bind, table: str) -> set:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "smb_servers" not in tables:
        op.create_table(
            "smb_servers",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("alias", sa.String(length=32), nullable=False),
            sa.Column("label", sa.String(length=128), nullable=True),
            sa.Column("host", sa.String(length=256), nullable=False),
            sa.Column("port", sa.Integer(), server_default="445", nullable=True),
            sa.Column("default_domain", sa.String(length=128), nullable=True),
            sa.Column(
                "credential_set",
                sa.String(length=24),
                server_default="DEFAULT",
                nullable=False,
            ),
            sa.Column("shares_json", sa.Text(), server_default="[]", nullable=False),
            sa.Column(
                "auth_protocol",
                sa.String(length=16),
                server_default="ntlm",
                nullable=False,
            ),
            sa.Column(
                "require_encryption", sa.Boolean(), server_default="0", nullable=True
            ),
            sa.Column("enabled", sa.Boolean(), server_default="1", nullable=True),
            sa.Column("sort_order", sa.Integer(), server_default="0", nullable=True),
            sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_test_ok", sa.Boolean(), nullable=True),
            sa.Column("last_test_error", sa.String(length=64), nullable=True),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "alias", name="uq_smb_servers_tenant_alias"
            ),
            sa.UniqueConstraint("tenant_id", "host", name="uq_smb_servers_tenant_host"),
        )
        op.create_index(
            "ix_smb_servers_tenant_id", "smb_servers", ["tenant_id"], unique=False
        )

    if "smb_settings" not in tables:
        return
    old_cols = _columns(bind, "smb_settings")
    if "host" not in old_cols:
        return  # already migrated (or created fresh by create_all)

    # Copy each configured single-server row into smb_servers (only when the
    # tenant has no server yet, so a re-run never duplicates).
    rows = bind.execute(
        sa.text(
            "SELECT tenant_id, host, port, default_domain, shares_json, auth_protocol, "
            "require_encryption, last_test_at, last_test_ok, last_test_error, "
            "updated_by_user_id FROM smb_settings"
        )
    ).fetchall()
    for r in rows:
        host = (r.host or "").strip().lower()
        if not host:
            continue
        exists = bind.execute(
            sa.text("SELECT 1 FROM smb_servers WHERE tenant_id = :t LIMIT 1"),
            {"t": r.tenant_id},
        ).first()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO smb_servers (id, tenant_id, alias, label, host, port, "
                "default_domain, credential_set, shares_json, auth_protocol, "
                "require_encryption, enabled, sort_order, last_test_at, last_test_ok, "
                "last_test_error, updated_by_user_id) VALUES (:id, :t, :alias, NULL, "
                ":host, :port, :dom, 'DEFAULT', :shares, :proto, :enc, :enabled, 0, "
                ":lta, :lto, :lte, :upd)"
            ),
            {
                "id": str(uuid.uuid4()),
                "t": r.tenant_id,
                "alias": _alias_from_host(host),
                "host": host,
                "port": r.port or 445,
                "dom": r.default_domain,
                "shares": r.shares_json or "[]",
                "proto": r.auth_protocol or "ntlm",
                "enc": bool(r.require_encryption),
                "enabled": True,
                "lta": r.last_test_at,
                "lto": r.last_test_ok,
                "lte": r.last_test_error,
                "upd": r.updated_by_user_id,
            },
        )

    with op.batch_alter_table("smb_settings") as batch:
        for col in _MOVED:
            if col in old_cols:
                batch.drop_column(col)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "smb_settings" in tables and "host" not in _columns(bind, "smb_settings"):
        with op.batch_alter_table("smb_settings") as batch:
            batch.add_column(sa.Column("host", sa.String(length=256), nullable=True))
            batch.add_column(
                sa.Column("port", sa.Integer(), server_default="445", nullable=True)
            )
            batch.add_column(
                sa.Column("default_domain", sa.String(length=128), nullable=True)
            )
            batch.add_column(
                sa.Column(
                    "shares_json", sa.Text(), server_default="[]", nullable=False
                )
            )
            batch.add_column(
                sa.Column(
                    "auth_protocol",
                    sa.String(length=16),
                    server_default="ntlm",
                    nullable=False,
                )
            )
            batch.add_column(
                sa.Column(
                    "require_encryption",
                    sa.Boolean(),
                    server_default="0",
                    nullable=True,
                )
            )
            batch.add_column(
                sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(sa.Column("last_test_ok", sa.Boolean(), nullable=True))
            batch.add_column(
                sa.Column("last_test_error", sa.String(length=64), nullable=True)
            )
        # Only the first server of each tenant fits the single-server schema.
        if "smb_servers" in tables:
            servers = bind.execute(
                sa.text(
                    "SELECT tenant_id, host, port, default_domain, shares_json, "
                    "auth_protocol, require_encryption FROM smb_servers "
                    "ORDER BY sort_order, alias"
                )
            ).fetchall()
            done = set()
            for s in servers:
                if s.tenant_id in done:
                    continue
                done.add(s.tenant_id)
                bind.execute(
                    sa.text(
                        "UPDATE smb_settings SET host = :host, port = :port, "
                        "default_domain = :dom, shares_json = :shares, "
                        "auth_protocol = :proto, require_encryption = :enc "
                        "WHERE tenant_id = :t"
                    ),
                    {
                        "host": s.host,
                        "port": s.port,
                        "dom": s.default_domain,
                        "shares": s.shares_json,
                        "proto": s.auth_protocol,
                        "enc": s.require_encryption,
                        "t": s.tenant_id,
                    },
                )
    if "smb_servers" in tables:
        op.drop_index("ix_smb_servers_tenant_id", table_name="smb_servers")
        op.drop_table("smb_servers")
