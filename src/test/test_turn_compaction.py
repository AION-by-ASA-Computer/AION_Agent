"""Tests for intra-turn tool truncation and budget helpers."""
from __future__ import annotations

import os
from unittest.mock import patch

from src.runtime.turn_compaction import truncate_tool_result


def test_truncate_tool_result_caps_huge_output():
    with patch.dict(os.environ, {"AION_TOOL_RESULT_MAX_CHARS": "1000"}, clear=False):
        big = "x" * 5000
        out = truncate_tool_result(big, tool_name="mail_fetch")
        assert len(out) < 5000
        assert "troncato" in out.lower()
