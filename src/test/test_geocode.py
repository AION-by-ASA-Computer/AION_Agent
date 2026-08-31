"""Unit tests for geocode tool (mocked Nominatim)."""

from __future__ import annotations

import pytest

from src.tools.geocode import geocode_place_sync, haversine_km


def test_haversine_km_same_point():
    assert haversine_km(35.0, 139.0, 35.0, 139.0) == 0.0


def test_geocode_place_picks_worship_over_shop(monkeypatch):
    worship = {
        "lat": "32.7830",
        "lon": "130.6586",
        "display_name": "高橋稲荷神社, 熊本市西区, 熊本県, 日本",
        "type": "place_of_worship",
        "class": "amenity",
        "importance": 0.4,
    }
    shop = {
        "lat": "39.2291",
        "lon": "140.1435",
        "display_name": "高橋美容室, 秋田県, 日本",
        "type": "hairdresser",
        "class": "shop",
        "importance": 0.2,
    }

    def fake_search(query, *, country_code, limit, client=None):
        return [shop, worship]

    monkeypatch.setattr("src.tools.geocode._nominatim_search", fake_search)
    monkeypatch.setattr("src.tools.geocode._rate_limit", lambda: None)

    out = geocode_place_sync(
        "Takahashi Inari Jinja, Kumamoto, Japan",
        country_code="jp",
        validate_contains="熊本",
    )
    assert out["ok"] is True
    assert out["lat"] == pytest.approx(32.7830)
    assert out["validated"] is True


def test_geocode_place_uses_fallback(monkeypatch):
    calls: list[str] = []

    def fake_search(query, *, country_code, limit, client=None):
        calls.append(query)
        if "笠間稲荷" in query:
            return [
                {
                    "lat": "36.3854725",
                    "lon": "140.2543843",
                    "display_name": "笠間稲荷神社, 茨城県",
                    "type": "place_of_worship",
                    "importance": 0.5,
                }
            ]
        return []

    monkeypatch.setattr("src.tools.geocode._nominatim_search", fake_search)
    monkeypatch.setattr("src.tools.geocode._rate_limit", lambda: None)

    out = geocode_place_sync(
        "Kasama Inari Jinja, Ibaraki, Japan",
        fallback_query="笠間稲荷神社, 茨城県",
        country_code="jp",
    )
    assert out["ok"] is True
    assert len(calls) >= 2
    assert "笠間稲荷" in out["query_used"]


def test_geocode_rejects_point_outside_country_bbox(monkeypatch):
    def fake_search(query, *, country_code, limit, client=None):
        return [
            {
                "lat": "48.8566",
                "lon": "2.3522",
                "display_name": "Paris, France",
                "type": "city",
                "importance": 0.9,
            }
        ]

    monkeypatch.setattr("src.tools.geocode._nominatim_search", fake_search)
    monkeypatch.setattr("src.tools.geocode._rate_limit", lambda: None)

    out = geocode_place_sync("Paris", country_code="jp")
    assert out["ok"] is False
