"""Unit tests for pptxgenjs lint_deck_script (layout/coord preflight)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.skill_registry import skill_registry


def test_lint_catches_layout_wide_coords_on_default_16x9(tmp_path):
    from src.skill_registry import skill_registry

    scripts_dir = skill_registry.get_skill_scripts_dir("pptx")
    if not scripts_dir:
        pytest.skip("pptx skill not installed")
    lint_js = scripts_dir / "pptxgenjs" / "lint_deck_script.js"
    assert lint_js.is_file()

    bad = tmp_path / "bad_deck.js"
    bad.write_text(
        """
const pres = {};
pres.addSlide = () => ({ addShape: () => {} });
// no pres.layout — uses 16x9 default
const slide = pres.addSlide();
slide.addShape('rect', { x: 0, y: 0, w: 13.33, h: 7.5 });
slide.addShape('rect', { x: 0, y: 7.1, w: 10, h: 0.4 });
""".strip()
        + "\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        ["node", str(lint_js), str(bad)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "LAYOUT_16x9" in combined or "13.33" in combined
    assert "bindLayout" in combined or "LAYOUT_WIDE" in combined


def test_lint_passes_when_layout_matches_coords(tmp_path):
    from src.skill_registry import skill_registry

    scripts_dir = skill_registry.get_skill_scripts_dir("pptx")
    if not scripts_dir:
        pytest.skip("pptx skill not installed")
    lint_js = scripts_dir / "pptxgenjs" / "lint_deck_script.js"
    good = tmp_path / "good_deck.js"
    good.write_text(
        """
const pres = { layout: null };
pres.layout = "LAYOUT_WIDE";
const slide = { background: null };
slide.background = { color: "0A0A0A" };
slide.addText = () => {};
slide.addText("x", { x: 0.5, y: 0.5, w: 12, h: 6 });
""".strip()
        + "\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(lint_js), str(good)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
