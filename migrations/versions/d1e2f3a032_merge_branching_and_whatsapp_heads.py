"""Merge delle due head: conversation_branching e whatsapp_pending_media.

Revision ID: d1e2f3a032
Revises: b1r2n3c030, c1d2e3f031

Entrambe le catene partivano da a9b0c1d029; nessuna modifica di schema.
"""

from typing import Sequence, Union


revision: str = "d1e2f3a032"
down_revision: Union[str, Sequence[str], None] = ("b1r2n3c030", "c1d2e3f031")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
