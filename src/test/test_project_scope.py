"""Project scope tests (Mnemos era)."""

from __future__ import annotations

from src.memory.mnemos.scope import project_scope, sanitize_project_slug


def test_project_scope_key() -> None:
    scope = project_scope("default", "finance_app")
    assert scope.scope_type == "project"
    assert scope.scope_key == "finance_app"


def test_sanitize_slug() -> None:
    assert sanitize_project_slug("Finance-App") == "finance-app"
