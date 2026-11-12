"""Merge the two heads: session_charts and service_accounts.

Revision ID: h6m7r8g036
Revises: c4a7r8t035, g5b6c7d035

Both chains start from f4a5b6c034 (merged into main by separate PRs). With two
heads ``alembic upgrade head`` aborts with "Multiple heads are present", so fresh
installs and upgrades (``upgrade_runner.py``) skipped every migration. This
revision only joins the chains: no schema change.
"""

from typing import Sequence, Union


revision: str = "h6m7r8g036"
down_revision: Union[str, Sequence[str], None] = ("c4a7r8t035", "g5b6c7d035")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: the parent revisions touch unrelated tables."""
    pass


def downgrade() -> None:
    """No-op: downgrading splits the history back into the two parent heads."""
    pass
