"""Default gate for session sandbox package install."""
from __future__ import annotations

import os

from src.tools import session_venv


def test_pip_install_allowed_by_default(monkeypatch):
    monkeypatch.delenv("AION_SANDBOX_ALLOW_PACKAGE_INSTALL", raising=False)
    assert session_venv._pip_install_allowed() is True


def test_pip_install_disabled_when_env_zero(monkeypatch):
    monkeypatch.setenv("AION_SANDBOX_ALLOW_PACKAGE_INSTALL", "0")
    assert session_venv._pip_install_allowed() is False
