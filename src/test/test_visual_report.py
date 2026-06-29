"""Tests for visual report HTML generation."""

from src.research.visual_report import generate_visual_report


def test_visual_report_contains_sidebar_and_print_css():
    html = generate_visual_report(
        question="What is Python?",
        report_markdown="## Overview\n\nPython is a programming language.\n\n## Details\n\nMore text here.",
        sources=[{"url": "https://example.com", "title": "Example", "image": ""}],
        stats={"Duration": "10s", "Rounds": 2},
        category="howto",
        session_id="test-session-1",
    )
    assert "AION Agent" in html
    assert "Deep Research Report" in html
    assert "@media print" in html
    assert "sidebar" in html.lower() or "toc" in html.lower()
    assert "Overview" in html
