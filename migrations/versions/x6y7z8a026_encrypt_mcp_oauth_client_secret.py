"""Cifra il client_secret in mcp_server_configs.oauth_config (AES-GCM a riposo).

Revision ID: x6y7z8a026
Revises: w5x6y7z025
"""

import logging
import os
from typing import Callable, Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


logger = logging.getLogger("alembic.runtime.migration")

revision: str = "x6y7z8a026"
down_revision: Union[str, None] = "w5x6y7z025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "mcp_server_configs"


def _rewrite(transform: Callable[[Optional[str]], Optional[str]]) -> None:
    # Alembic da CLI non carica .env: senza chiave si cifrerebbe con la chiave di
    # sviluppo, illeggibile poi dal backend. Le righe restano in chiaro (lette
    # comunque come legacy) e vengono cifrate alla prima scrittura ORM.
    if not (os.getenv("AION_CREDENTIAL_ENCRYPTION_KEY") or "").strip():
        logger.warning(
            "AION_CREDENTIAL_ENCRYPTION_KEY non impostata: salto %s su %s",
            transform.__name__,
            _TABLE,
        )
        return
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    rows = bind.execute(
        sa.text(f"SELECT id, oauth_config FROM {_TABLE} WHERE oauth_config IS NOT NULL")
    ).fetchall()
    for row_id, raw in rows:
        new = transform(raw)
        if new != raw:
            bind.execute(
                sa.text(f"UPDATE {_TABLE} SET oauth_config = :cfg WHERE id = :id"),
                {"cfg": new, "id": row_id},
            )


def upgrade() -> None:
    from src.data.encrypted_types import encrypt_oauth_config_json

    _rewrite(encrypt_oauth_config_json)


def downgrade() -> None:
    from src.data.encrypted_types import decrypt_oauth_config_json

    _rewrite(decrypt_oauth_config_json)
