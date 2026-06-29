"""SQL QueryMemory helpers (embedding cosine, feature flag)."""
from __future__ import annotations

import os
from unittest.mock import patch

import numpy as np

from src.memory.sql_query_memory.embedding import cosine_similarity
from src.memory.sql_query_memory.service import sql_query_memory_enabled


def test_cosine_similarity_identical_vectors():
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert cosine_similarity(v, v) == 1.0


def test_cosine_similarity_orthogonal():
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert cosine_similarity(a, b) == 0.0


def test_sql_query_memory_enabled_env():
    with patch.dict(os.environ, {"AION_SQL_QM_ENABLED": "0"}, clear=False):
        assert sql_query_memory_enabled() is False
    with patch.dict(os.environ, {"AION_SQL_QM_ENABLED": "1"}, clear=False):
        assert sql_query_memory_enabled() is True
