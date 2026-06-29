"""SQL QueryMemory auto-learn env gate."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.runtime.query_memory_hooks import sql_qm_auto_learn_enabled


def test_auto_learn_off_by_default_env() -> None:
    with patch.dict(os.environ, {"AION_SQL_QM_AUTO_LEARN": "0"}, clear=False):
        assert sql_qm_auto_learn_enabled(tenant_sql_auto_learn=True) is False


def test_auto_learn_requires_env_and_tenant() -> None:
    with patch.dict(os.environ, {"AION_SQL_QM_AUTO_LEARN": "1"}, clear=False):
        assert sql_qm_auto_learn_enabled(tenant_sql_auto_learn=True) is True
        assert sql_qm_auto_learn_enabled(tenant_sql_auto_learn=False) is False
