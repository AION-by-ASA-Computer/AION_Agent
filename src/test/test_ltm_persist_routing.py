"""LTM persist validation (wing/room/importance — no user-text regex)."""
from __future__ import annotations

from src.memory.ltm_orchestrator import _filter_ltm_drawer, _is_project_wing


def test_project_wing_detection() -> None:
    assert _is_project_wing("wing_proj_aion_am")
    assert not _is_project_wing("wing_user_demo")


def test_filter_rejects_low_importance() -> None:
    assert (
        _filter_ltm_drawer(
            {
                "wing": "wing_user_x",
                "room": "general",
                "content": "short but long enough text here",
                "importance": 1,
            },
            "wing_user_x",
        )
        is None
    )


def test_filter_normalizes_project_room() -> None:
    out = _filter_ltm_drawer(
        {
            "wing": "wing_proj_default",
            "room": "join_paths",
            "content": "Verified join between ordini and clienti on id_cliente.",
            "importance": 3,
        },
        "wing_user_x",
    )
    assert out is not None
    assert out["room"] == "join_paths"


def test_filter_rejects_invalid_project_room() -> None:
    out = _filter_ltm_drawer(
        {
            "wing": "wing_proj_default",
            "room": "company_facts",
            "content": "Aion was founded in 2025 according to the user request.",
            "importance": 5,
        },
        "wing_user_x",
    )
    assert out is None
