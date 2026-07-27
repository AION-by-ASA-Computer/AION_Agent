"""Tests for Pi custom compaction helper."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.runtime.pi_runtime.pi_compaction import (
    pi_custom_compaction_enabled,
    summarize_for_pi_compaction,
)


def test_pi_custom_compaction_flag_default_off():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AION_PI_CUSTOM_COMPACTION", None)
        assert not pi_custom_compaction_enabled()


def test_summarize_appends_tool_blocks(tmp_path, monkeypatch):
    sid = "test-pi-compact01"
    monkeypatch.setenv("AION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AION_TOOL_LEDGER_ENABLED", "1")

    from src.runtime.tool_ledger import LedgerEntry, append_ledger_entry

    append_ledger_entry(
        sid,
        LedgerEntry(
            seq=1,
            ts=1.0,
            tool="web_fetch_page",
            target="Group_A",
            ok=True,
            chars=9000,
            path="derived/tool_results/0001_web_fetch_page_x.txt",
        ),
    )

    with patch(
        "src.runtime.pi_runtime.pi_compaction.complete_text_sync",
        return_value="## Goal\nFinish excel",
    ):
        out = summarize_for_pi_compaction(
            session_id=sid,
            transcript="[User]: build excel\n[Tool result]: big data",
        )

    assert "Finish excel" in out["summary"]
    assert "<tool-trace>" in out["summary"]
    assert "web_fetch_page" in out["summary"]
    assert out["details"]["toolLedger"]
