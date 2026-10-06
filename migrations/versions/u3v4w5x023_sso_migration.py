"""SSO migration: auth_settings, user columns, unique constraint.

Revision ID: u3v4w5x023
Revises: t2u3v4w022
"""

from typing import Sequence, Union
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = "u3v4w5x023"
down_revision: Union[str, None] = "t2u3v4w022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # -----------------------------------------------------------------------
    # 1.1  Tabella auth_settings (una riga per tenant)
    # -----------------------------------------------------------------------
    if "auth_settings" not in tables:
        op.create_table(
            "auth_settings",
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("login_mode", sa.String(length=16), server_default="password", nullable=False),
            sa.Column("sso_origin", sa.String(length=16), nullable=True),
            sa.Column("migration_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("migration_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("clear_password_on_link", sa.Boolean(), server_default="1", nullable=False),
            sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("tenant_id"),
        )

    # -----------------------------------------------------------------------
    # 1.2  Nuove colonne su users
    # -----------------------------------------------------------------------
    existing_user_cols = {c["name"] for c in inspector.get_columns("users")}

    if "sso_migration_exempt" not in existing_user_cols:
        op.add_column(
            "users",
            sa.Column(
                "sso_migration_exempt",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            ),
        )

    if "temp_password_expires_at" not in existing_user_cols:
        op.add_column(
            "users",
            sa.Column(
                "temp_password_expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    # -----------------------------------------------------------------------
    # 1.3  Vincolo unico (tenant_id, user_id, provider) su user_sso_identities
    # -----------------------------------------------------------------------
    # Prima deduplicare mantenendo la riga con last_login_at più recente.
    if "user_sso_identities" in tables:
        existing_indices = {idx["name"] for idx in inspector.get_indexes("user_sso_identities")}
        existing_ucs = {
            uc["name"]
            for uc in inspector.get_unique_constraints("user_sso_identities")
        }

        if "uq_user_sso_identities_user_provider" not in existing_ucs | existing_indices:
            # Deduplicazione: per ogni (tenant_id, user_id, provider) conserva
            # la riga con id più grande o last_login_at più recente.
            # SQLite non supporta DELETE con subquery sulla stessa tabella,
            # quindi usiamo una CTE o un approccio a due step.
            try:
                bind.execute(text("""
                    DELETE FROM user_sso_identities
                    WHERE id NOT IN (
                        SELECT id FROM (
                            SELECT id,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY tenant_id, user_id, provider
                                       ORDER BY COALESCE(last_login_at, '1970-01-01') DESC, id DESC
                                   ) AS rn
                            FROM user_sso_identities
                        ) ranked
                        WHERE rn = 1
                    )
                """))
            except Exception:
                pass  # Se fallisce (es. tabella vuota), ignora

            try:
                op.create_unique_constraint(
                    "uq_user_sso_identities_user_provider",
                    "user_sso_identities",
                    ["tenant_id", "user_id", "provider"],
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 1.4  Backfill auth_settings
    # -----------------------------------------------------------------------
    # Se esiste un sso_providers con enabled=1 e validated_at valorizzato,
    # imposta login_mode = provider e sso_origin appropriato.
    try:
        tenants = list(bind.execute(text("SELECT id FROM tenants")))
        for (tenant_id,) in tenants:
            # Controlla se esiste già una riga in auth_settings per questo tenant
            existing_setting = bind.execute(
                text("SELECT tenant_id FROM auth_settings WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).fetchone()
            if existing_setting:
                continue

            # Cerca provider abilitato e validato
            provider_row = bind.execute(
                text("""
                    SELECT provider, validated_by_user_id
                    FROM sso_providers
                    WHERE tenant_id = :tid AND enabled = 1 AND validated_at IS NOT NULL
                    LIMIT 1
                """),
                {"tid": tenant_id},
            ).fetchone()

            login_mode = "password"
            sso_origin = None
            migration_started_at = None

            if provider_row:
                login_mode = provider_row[0]
                validated_by = provider_row[1]

                # origin = migration se ci sono utenti con password diversi dall'admin validante
                has_other_users = bind.execute(
                    text("""
                        SELECT 1 FROM users
                        WHERE tenant_id = :tid
                          AND password_hash IS NOT NULL
                          AND id != :admin_id
                        LIMIT 1
                    """),
                    {"tid": tenant_id, "admin_id": validated_by or ""},
                ).fetchone()

                sso_origin = "migration" if has_other_users else "first_setup"
                if sso_origin == "migration":
                    migration_started_at = datetime.now(timezone.utc)

            now = datetime.now(timezone.utc)
            bind.execute(
                text("""
                    INSERT INTO auth_settings
                        (tenant_id, login_mode, sso_origin, migration_started_at, updated_at)
                    VALUES (:tid, :mode, :origin, :started, :now)
                """),
                {
                    "tid": tenant_id,
                    "mode": login_mode,
                    "origin": sso_origin,
                    "started": migration_started_at,
                    "now": now,
                },
            )
    except Exception as e:
        # Backfill non bloccante: il servizio funziona anche senza
        import logging
        logging.getLogger("alembic.migration").warning(
            "auth_settings backfill parziale: %s", e
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Rimuovi vincolo unico da user_sso_identities
    existing_ucs = {
        uc["name"]
        for uc in inspector.get_unique_constraints("user_sso_identities")
    }
    if "uq_user_sso_identities_user_provider" in existing_ucs:
        try:
            op.drop_constraint(
                "uq_user_sso_identities_user_provider",
                "user_sso_identities",
                type_="unique",
            )
        except Exception:
            pass

    # Rimuovi colonne da users (SQLite non supporta DROP COLUMN nella versione
    # precedente, quindi usiamo try/except)
    try:
        op.drop_column("users", "temp_password_expires_at")
    except Exception:
        pass

    try:
        op.drop_column("users", "sso_migration_exempt")
    except Exception:
        pass

    # Rimuovi auth_settings
    try:
        op.drop_table("auth_settings")
    except Exception:
        pass
