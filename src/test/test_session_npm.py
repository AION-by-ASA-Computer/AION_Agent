"""session_npm validation."""

from __future__ import annotations

import pytest

from src.tools.session_npm import _validate_package_names


def test_validate_package_names_accepts_docx():
    assert _validate_package_names(["docx"]) == ["docx"]


def test_validate_package_names_rejects_shell():
    with pytest.raises(ValueError):
        _validate_package_names(["docx; rm -rf /"])
