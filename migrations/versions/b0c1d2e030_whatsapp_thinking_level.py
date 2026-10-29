"""Canale WhatsApp: whatsapp_channels.default_thinking_level.

Livello di pensiero (off | min | medium | max) usato nei turni WhatsApp;
NULL = default di sistema. Idempotente: salta se tabella/colonna già presente
(es. DB creato con ``create_all`` dal modello aggiornato).

Revision ID: b0c1d2e030
Revises: a9b0c1d029
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e030"
down_revision: Union[str, None] = "a9b0c1d029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "whatsapp_channels"
_COLUMN = "default_thinking_level"


def _existing_columns() -> set:
    """Nomi colonna della tabella, vuoto se la tabella non esiste ancora."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    cols = _existing_columns()
    if cols and _COLUMN not in cols:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(8), nullable=True))


def downgrade() -> None:
    if _COLUMN in _existing_columns():
        # batch_alter_table: SQLite non supporta DROP COLUMN su tutte le versioni.
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
