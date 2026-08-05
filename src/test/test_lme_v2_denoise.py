"""Tests for LME-V2 accessibility-tree denoising."""

from __future__ import annotations

from src.benchmarks.longmemeval_v2.denoise import (
    collect_boilerplate,
    denoise_tree,
    filter_boilerplate,
    strip_node_line,
)


def test_strip_node_line_removes_ids_and_noise_attrs():
    raw = (
        "[113] combobox 'Search' value='Hardware Assets', clickable, visible, "
        "focused, autocomplete='both', hasPopup='listbox'"
    )
    cleaned = strip_node_line(raw)
    assert "[113]" not in cleaned
    assert "clickable" not in cleaned
    assert "combobox 'Search' value='Hardware Assets'" in cleaned


def test_denoise_tree_drops_empty_containers():
    tree = "generic\nmenuitem 'Incident Mobile', visible\nregion ''"
    lines = denoise_tree(tree)
    assert any("Incident Mobile" in ln for ln in lines)
    assert not any(ln.strip() == "generic" for ln in lines)


def test_collect_boilerplate_detects_chrome():
    chrome_line = "navigation 'Global skip links'"
    states = [
        [chrome_line],
        [chrome_line],
        [chrome_line],
        ["menuitem 'Save'"],
    ]
    boiler = collect_boilerplate(states, threshold=0.6)
    assert chrome_line in boiler
    assert "menuitem 'Save'" not in boiler


def test_filter_boilerplate():
    lines = ["a", "b", "c"]
    assert filter_boilerplate(lines, {"b"}) == ["a", "c"]
