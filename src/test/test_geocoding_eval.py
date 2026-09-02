"""Live geocoding eval against evals/geocoding/cases/*.yaml (requires network)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from src.tools.geocode import geocode_place_sync, haversine_km

REPO_ROOT = Path(__file__).resolve().parents[2]
INARI_CASES = REPO_ROOT / "evals" / "geocoding" / "cases" / "inari_shrines_jp.yaml"


def _load_cases(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("cases") or [])


@pytest.mark.skipif(
    not os.getenv("AION_GEOCODING_LIVE"),
    reason="Set AION_GEOCODING_LIVE=1 for live Nominatim eval",
)
def test_inari_shrines_golden_live():
    cases = _load_cases(INARI_CASES)
    assert len(cases) >= 10

    passed = 0
    rows: list[str] = []
    for case in cases:
        cid = case["id"]
        ref_lat = float(case["lat"])
        ref_lon = float(case["lon"])
        max_km = float(case.get("max_distance_km") or 0.5)

        out = geocode_place_sync(
            str(case.get("query") or ""),
            fallback_query=str(case.get("query_ja") or ""),
            country_code="jp",
        )
        if not out.get("ok"):
            rows.append(f"FAIL {cid}: {out.get('error')}")
            continue

        dist = haversine_km(ref_lat, ref_lon, float(out["lat"]), float(out["lon"]))
        ok = dist <= max_km and out.get("validated", True)
        if ok:
            passed += 1
        mark = "PASS" if ok else "FAIL"
        rows.append(
            f"{mark} {cid}: {dist:.2f}km validated={out.get('validated')} "
            f"| {out.get('display_name', '')[:60]}"
        )

    summary = f"{passed}/{len(cases)} within tolerance"
    print("\n".join(rows))
    print(summary)
    assert passed >= len(cases) - 1, summary
