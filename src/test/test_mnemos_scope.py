"""Mnemos scope resolution tests."""

from __future__ import annotations

from src.memory.mnemos.scope import (
    project_scope,
    resolve_scope_for_write,
    resolve_scopes_for_wake,
    sanitize_project_slug,
    user_scope,
)


def test_sanitize_project_slug() -> None:
    assert sanitize_project_slug("My Project!") == "my_project"


def test_resolve_scope_for_write_project_requires_active() -> None:
    scope = resolve_scope_for_write(
        tenant_id="default",
        user_id="alice",
        scope_name="project",
        active_project_slug=None,
    )
    assert scope.scope_type == "user"


def test_resolve_scope_for_write_project_with_slug() -> None:
    scope = resolve_scope_for_write(
        tenant_id="default",
        user_id="alice",
        scope_name="project",
        active_project_slug="acme",
    )
    assert scope.scope_type == "project"
    assert scope.scope_key == "acme"


def test_wake_scopes_include_user_and_project() -> None:
    scopes = resolve_scopes_for_wake(
        tenant_id="default",
        user_id="alice",
        active_project_slug="acme",
    )
    types = [s.scope_type for s in scopes]
    assert types == ["user", "project"]
    assert scopes[0] == user_scope("default", "alice")
    assert scopes[1] == project_scope("default", "acme")
