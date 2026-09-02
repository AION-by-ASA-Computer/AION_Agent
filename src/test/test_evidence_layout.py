"""Tests for Word evidence figure layout helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

_SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "config_proprietary"
    / "skills"
    / "docx"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS))

from report.evidence_layout import (  # noqa: E402
    DEFAULT_MAX_HEIGHT_IN,
    DEFAULT_MAX_WIDTH_IN,
    estimated_display_height_inches,
    fit_image_width_inches,
)


def test_fit_image_width_caps_tall_portrait(tmp_path):
    # Simulate full-page decree screenshot (aspect ~1.4)
    path = tmp_path / "tall.png"
    Image.new("RGB", (1000, 1400), color=(255, 255, 255)).save(path)
    w = fit_image_width_inches(path)
    h = estimated_display_height_inches(path)
    assert w <= DEFAULT_MAX_WIDTH_IN
    assert h <= DEFAULT_MAX_HEIGHT_IN + 0.01


def test_fit_image_width_preserves_wide_crop(tmp_path):
    path = tmp_path / "wide.png"
    img = Image.new("RGB", (1200, 400), color=(255, 255, 255))
    for x in range(100, 1100):
        for y in range(150, 250):
            img.putpixel((x, y), (0, 0, 0))
    img.save(path)
    w = fit_image_width_inches(path)
    assert w == pytest.approx(DEFAULT_MAX_WIDTH_IN, rel=0.01)
