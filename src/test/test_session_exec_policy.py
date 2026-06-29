"""Exec allowlist policy guards (python script path, exec disabled)."""

from __future__ import annotations

import pytest

from src.tools.session_exec import (
    ExecAllowlistError,
    _validate_argv_against_allowlist,
    _validate_python_argv,
)


def test_python_rejects_inline_c():
    with pytest.raises(ExecAllowlistError, match="-c"):
        _validate_python_argv(["python", "-c", "print(1)"])


def test_python_requires_scripts_prefix():
    with pytest.raises(ExecAllowlistError, match="scripts/"):
        _validate_python_argv(["python", "/tmp/evil.py"])
    _validate_python_argv(
        ["python", "scripts/office/unpack.py", "uploads/x.docx", "unpacked/"]
    )


def test_wren_argv_matches_allowlist():
    allowlist = [{"executable": "wren", "argv_prefix": []}]
    for argv in (
        ["wren", "skills", "get", "onboarding"],
        ["wren", "skills", "list"],
        ["wren", "ask", "how many users?", "--guided"],
        ["wren", "--sql", "SELECT 1"],
        ["wren", "query", "--sql", "SELECT 1"],
        ["wren", "dry-plan", "--sql", "SELECT 1"],
        ["wren", "context", "show"],
        ["wren", "profile", "list"],
        ["wren", "docs", "connection-info", "postgres"],
        ["wren", "--help"],
    ):
        entry = _validate_argv_against_allowlist(argv, allowlist)
        assert entry["executable"] == "wren"


def test_unpack_argv_matches_dev_allowlist():
    allowlist = [
        {
            "executable": "python",
            "argv_prefix": [],
            "validate_path_positions": [1, 2, 3],
        },
    ]
    argv = [
        "python",
        "scripts/office/unpack.py",
        "uploads/4a5bfb3876_AION_Forecasting_Proposal_v3.docx",
        "unpacked/",
    ]
    entry = _validate_argv_against_allowlist(argv, allowlist)
    assert entry["executable"] == "python"
    _validate_python_argv(argv)
