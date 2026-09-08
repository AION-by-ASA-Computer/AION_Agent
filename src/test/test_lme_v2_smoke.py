"""Tests for LME-V2 smoke fixtures and metrics (no HF download)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.benchmarks.longmemeval_v2.metrics import aggregate_metrics
from src.benchmarks.longmemeval_v2.prepare import (
    collect_haystack_trajectory_ids,
    normalize_ability,
    prepare_dataset,
    trajectory_text_chunks,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lme_v2_smoke"


@pytest.fixture
def lme_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AION_BENCHMARK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AION_LME_V2_TIER", "small")
    return tmp_path


def test_trajectory_text_chunks():
    traj = {
        "goal": "Assign work to relevant agents",
        "states": [
            {
                "thought": "Open the incidents list",
                "accessibility_tree": (
                    "menuitem 'Closed', visible\n"
                    "menuitem 'Incident Mobile', visible\n"
                    "menuitem 'Incident Portal', visible"
                ),
            }
        ],
    }
    chunks = trajectory_text_chunks(traj, max_states=3)
    assert any("Assign work" in c for c in chunks)
    assert any("Incident Mobile" in c for c in chunks)


def test_extract_ui_labels_prioritizes_menuitems():
    from src.benchmarks.longmemeval_v2.prepare import _extract_ui_labels

    chrome = "\n".join(f"link 'Nav item {i}', visible" for i in range(60))
    tree = (
        f"{chrome}\n"
        "menuitem 'Incident Mobile', visible\n"
        "menuitem 'Incident Portal', visible\n"
        "menuitem 'My Open Incidents', visible"
    )
    labels = _extract_ui_labels(tree, limit=40)
    assert labels[:3] == ["Incident Mobile", "Incident Portal", "My Open Incidents"]


def test_menu_options_survives_mnemos_clamp():
    from src.memory.mnemos.store import _clamp_content

    from src.benchmarks.longmemeval_v2.prepare import trajectory_text_chunks

    chrome = "\n".join(f"link 'Nav item {i}', visible" for i in range(60))
    traj = {
        "states": [
            {
                "accessibility_tree": (
                    f"{chrome}\n"
                    "menuitem 'Incident Mobile', visible\n"
                    "menuitem 'Incident Portal', visible\n"
                    "menuitem 'My Open Incidents', visible"
                ),
            }
        ],
    }
    chunks = trajectory_text_chunks(traj, max_states=1)
    menu = next(c for c in chunks if c.startswith("menu_options:"))
    clamped = _clamp_content(menu)
    assert "Incident Mobile" in clamped
    assert "Incident Portal" in clamped
    assert "My Open Incidents" in clamped


def test_catalog_options_chunk_includes_pricing():
    from src.benchmarks.longmemeval_v2.prepare import trajectory_text_chunks

    traj = {
        "goal": "Order developer laptop",
        "states": [
            {
                "accessibility_tree": (
                    "\n".join(f"link 'Nav {i}', visible" for i in range(40))
                    + "\nradio '\\uf137 512 GB [add $300.00]', visible\n"
                    + "StaticText '512 GB [add $300.00]'\n"
                    + "StaticText '256 GB [add $100.00]'"
                ),
            }
        ],
    }
    chunks = trajectory_text_chunks(traj, max_states=1)
    assert any("catalog_options:" in c and "$300.00" in c for c in chunks)


def test_collect_haystack_trajectory_ids():
    haystack = {
        "q1": ["t1", "t2"],
        "q2": ["t2", "t3"],
    }
    assert collect_haystack_trajectory_ids(haystack) == ["t1", "t2", "t3"]
    assert collect_haystack_trajectory_ids(haystack, question_id="q1") == ["t1", "t2"]


def test_normalize_ability():
    assert normalize_ability("static_state_recall") == "static"
    assert normalize_ability("workflow_knowledge") == "workflow"


def test_prepare_from_fixture(lme_data_dir):
    result = prepare_dataset(fixture=FIXTURE)
    assert result["ready"] is True
    assert result["question_count"] == 3
    assert result["trajectory_count"] == 2


def test_aggregate_metrics():
    rows = [
        {"score": 1.0, "latency_sec": 0.1, "evidence": "abc", "ability": "static"},
        {"score": 0.0, "latency_sec": 0.2, "evidence": "def", "ability": "workflow"},
    ]
    m = aggregate_metrics(rows)
    assert m["case_count"] == 2
    assert m["accuracy_overall"] == 0.5
    assert "static" in m["accuracy_by_ability"]
