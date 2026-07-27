"""Wikipedia-aware web_fetch_page extraction."""

from __future__ import annotations

import json

import pytest

from src.runtime.native_tools import web_providers as wp


def test_parse_wikipedia_url():
    assert wp._parse_wikipedia_url(
        "https://en.wikipedia.org/wiki/2022_FIFA_World_Cup"
    ) == ("en", "2022 FIFA World Cup", None)


def test_parse_wikipedia_url_with_section_anchor():
    assert wp._parse_wikipedia_url(
        "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage#Mexico_vs_England"
    ) == ("en", "2026 FIFA World Cup knockout stage", "Mexico_vs_England")


def test_wikipedia_fetch_uses_api(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "query": {
                    "pages": {
                        "1": {
                            "extract": "The 2022 FIFA World Cup was held in Qatar. " * 200,
                        }
                    }
                }
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, timeout=None, headers=None):
            assert "w/api.php" in url
            assert params["titles"] == "2022 FIFA World Cup"
            return _Resp()

    monkeypatch.setattr(wp.httpx, "Client", _Client)
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")
    raw = wp.run_web_fetch_page("https://en.wikipedia.org/wiki/2022_FIFA_World_Cup")
    data = json.loads(raw)
    assert data["mode"] == "wikipedia_api"
    assert "Qatar" in data["text"]


def test_wikipedia_short_extract_falls_back_to_html(monkeypatch):
    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, timeout=None, headers=None):
            params = params or {}
            if params.get("prop") == "extracts":
                return _Resp(
                    {
                        "query": {
                            "pages": {
                                "1": {"extract": "Short lead paragraph only."},
                            }
                        }
                    }
                )
            if params.get("action") == "parse" and params.get("prop") == "text":
                return _Resp(
                    {
                        "parse": {
                            "text": {
                                "*": "<p>Mexico 2 - 0 South Africa. Goals: Quiñones 9, Jiménez 62.</p>"
                            }
                        }
                    }
                )
            raise AssertionError(f"unexpected params {params}")

    monkeypatch.setattr(wp.httpx, "Client", _Client)
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")
    raw = wp.run_web_fetch_page("https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_A")
    data = json.loads(raw)
    assert data["mode"] == "wikipedia_html"
    assert "Mexico 2" in data["text"]
    assert data.get("hint")


@pytest.mark.integration
def test_wikipedia_group_page_returns_substantial_text(monkeypatch):
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")
    raw = wp.run_web_fetch_page("https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_A")
    data = json.loads(raw)
    assert data.get("error") is None
    assert data["chars"] > 5000
    assert data["mode"] in ("wikipedia_html", "wikipedia_section")


def test_wikipedia_fetch_section_by_anchor(monkeypatch):
    calls: list[dict] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, timeout=None, headers=None):
            calls.append(dict(params or {}))
            if params.get("prop") == "sections":
                return _Resp(
                    {
                        "parse": {
                            "sections": [
                                {"index": "5", "anchor": "Mexico_vs_England", "line": "Mexico vs England"},
                            ]
                        }
                    }
                )
            if params.get("section") == "5":
                return _Resp(
                    {
                        "parse": {
                            "text": {
                                "*": "<p>Mexico 2 - 1 England. Attendance 87432.</p>"
                            }
                        }
                    }
                )
            raise AssertionError(f"unexpected params {params}")

    monkeypatch.setattr(wp.httpx, "Client", _Client)
    monkeypatch.setenv("AION_TOOL_RESULT_FORMAT", "json")
    raw = wp.run_web_fetch_page(
        "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage#Mexico_vs_England"
    )
    data = json.loads(raw)
    assert data["mode"] == "wikipedia_section"
    assert "Mexico 2" in data["text"]
    assert any(c.get("prop") == "sections" for c in calls)
    assert any(c.get("section") == "5" for c in calls)
