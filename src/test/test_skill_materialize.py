"""Skill package scripts materialized into session workspace."""

from __future__ import annotations

from src.tools.skill_materialize import materialize_skill_scripts


def test_materialize_unknown_skill():
    r = materialize_skill_scripts("sess-x", "no_such_skill_xyz")
    assert r.status == "not_found"
