"""Tests for promotional graphics capture helpers."""
from __future__ import annotations

import unittest

from src.tools.promo_capture import (
    CANVAS_PRESETS,
    _pick_template,
    list_canvas_presets,
    read_component_catalog,
    read_style_guide,
    _slug,
)


class TestPromoCapture(unittest.TestCase):
    def test_list_canvas_presets(self):
        presets = list_canvas_presets()
        self.assertGreaterEqual(len(presets), 4)
        ids = {p["id"] for p in presets}
        self.assertIn("instagram_square", ids)

    def test_read_style_guide_contains_css(self):
        guide = read_style_guide()
        self.assertIn("promo-root", guide)
        self.assertIn("--bg-canvas", guide)

    def test_slug(self):
        self.assertEqual(_slug("My Campaign!"), "my_campaign_")

    def test_instagram_square_dimensions(self):
        p = CANVAS_PRESETS["instagram_square"]
        self.assertEqual(p["width"], 1080)
        self.assertEqual(p["height"], 1080)

    def test_pick_bento_template(self):
        self.assertEqual(
            _pick_template("instagram_portrait", "bento_red"),
            "bento_portrait_red.html",
        )
        self.assertEqual(
            _pick_template("instagram_square", "bento_red"),
            "bento_square_red.html",
        )
        self.assertEqual(
            _pick_template("linkedin_post", "bento_red"),
            "bento_linkedin_red.html",
        )
        self.assertEqual(_pick_template("instagram_portrait", "minimal"), "react_post.html")

    def test_component_catalog(self):
        cat = read_component_catalog()
        self.assertIn("promo-bento--portrait", cat)

    def test_instagram_portrait_dimensions(self):
        p = CANVAS_PRESETS["instagram_portrait"]
        self.assertEqual(p["width"], 1080)
        self.assertEqual(p["height"], 1350)


if __name__ == "__main__":
    unittest.main()
