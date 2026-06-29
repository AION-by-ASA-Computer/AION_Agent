"""Scope resolution for SQL QueryMemory (shared vs per-user)."""
from __future__ import annotations

import os
from unittest.mock import patch

from src.memory.sql_query_memory.scope import (
    SHARED_SCOPE_KEY,
    datasource_key_from_env,
    effective_scope,
    env_default_scope,
    user_scope_key,
)


def test_effective_scope_project_override():
    assert effective_scope("shared", "per_user") == "shared"
    assert effective_scope("per_user", "shared") == "per_user"


def test_effective_scope_inherits_tenant_default():
    assert effective_scope("inherit", "shared") == "shared"
    assert effective_scope("inherit", "per_user") == "per_user"


def test_user_scope_key_shared_vs_per_user():
    assert user_scope_key("shared", "alice") == SHARED_SCOPE_KEY
    assert user_scope_key("per_user", "alice") == "alice"


def test_env_default_scope():
    with patch.dict(os.environ, {"AION_SQL_QM_DEFAULT_SCOPE": "shared"}, clear=False):
        assert env_default_scope() == "shared"
    with patch.dict(os.environ, {"AION_SQL_QM_DEFAULT_SCOPE": "invalid"}, clear=False):
        assert env_default_scope() == "per_user"


def test_datasource_key_from_postgres_url():
    with patch.dict(
        os.environ,
        {"POSTGRES_URL": "postgresql://u:p@dbhost.example:5432/sales_db"},
        clear=False,
    ):
        key = datasource_key_from_env("postgres_metadata_assistant")
        assert "dbhost.example" in key
        assert "sales_db" in key
