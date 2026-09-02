"""Geocoding via OpenStreetMap Nominatim (deterministic, no LLM)."""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("aion.geocode")

_last_request_at = 0.0
_rate_lock = threading.Lock()

# Rough WGS84 bounding boxes (lat_min, lat_max, lon_min, lon_max)
_COUNTRY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "jp": (24.0, 46.5, 122.0, 154.0),
    "it": (35.0, 48.0, 6.0, 19.5),
}

_PLACE_OF_WORSHIP = frozenset(
    {
        "place_of_worship",
        "religious",
        "temple",
        "shrine",
        "church",
        "chapel",
        "monastery",
    }
)

_UNRELIABLE_TYPES = frozenset(
    {
        "hairdresser",
        "beauty",
        "shop",
        "retail",
        "company",
        "office",
    }
)

_SHRINE_HINT_RE = re.compile(
    r"(jinja|taisha|shrine|inari|神社|稲荷|神宮|大社)",
    re.IGNORECASE,
)

_REGION_TOKEN_RE = re.compile(
    r"[\w\u3040-\u30ff\u4e00-\u9fff]+(?:県|府|道|市|区|町|村)",
)

_INARI_NEARBY_TYPES = frozenset(
    {
        "bus_stop",
        "station",
        "stop",
        "neighbourhood",
        "suburb",
        "quarter",
    }
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nominatim_base_url() -> str:
    return (
        os.getenv("AION_GEOCODING_NOMINATIM_URL", "https://nominatim.openstreetmap.org")
        .strip()
        .rstrip("/")
    )


def _user_agent() -> str:
    return (
        os.getenv("AION_GEOCODING_USER_AGENT", "").strip()
        or "AION-Agent/1.0 (+https://github.com/aion-agent; geocoding-mcp)"
    )


def _min_interval_sec() -> float:
    try:
        return max(0.0, float(os.getenv("AION_GEOCODING_MIN_INTERVAL_SEC", "1.1")))
    except ValueError:
        return 1.1


def _rate_limit() -> None:
    global _last_request_at
    interval = _min_interval_sec()
    with _rate_lock:
        now = time.monotonic()
        wait = interval - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _in_bbox(lat: float, lon: float, cc: str) -> bool:
    box = _COUNTRY_BBOX.get(cc.lower())
    if not box:
        return True
    lat_min, lat_max, lon_min, lon_max = box
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def _display_text(hit: dict[str, Any]) -> str:
    return str(hit.get("display_name") or "")


def _region_hints(*queries: str) -> set[str]:
    hints: set[str] = set()
    for query in queries:
        for token in _REGION_TOKEN_RE.findall(query or ""):
            token = token.strip()
            if not token:
                continue
            hints.add(token)
            if token.endswith(("県", "府", "道")):
                hints.add(token[:-1])
    return hints


def _extra_queries(primary: str, fallback: str, *, shrine_query: bool) -> list[str]:
    extras: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        q = re.sub(r"\s+", " ", (q or "").strip())
        if q and q not in seen:
            seen.add(q)
            extras.append(q)

    for q in (primary, fallback):
        if "," in q:
            add(q.replace(",", " "))

    if shrine_query and fallback:
        parts = [p.strip() for p in re.split(r"[,、]", fallback) if p.strip()]
        if len(parts) >= 2:
            name = parts[0]
            loc = parts[-1]
            loc_short = re.sub(r"(県|府|道)$", "", loc)
            stem = re.split(r"(神社|稲荷|神宮|大社)", name, maxsplit=1)[0].strip()
            if stem and loc_short:
                add(f"{stem} {loc_short} 稲荷")

    return extras


def _score_hit(
    hit: dict[str, Any],
    *,
    validate_contains: str,
    shrine_query: bool,
    region_hints: set[str],
) -> float:
    score = float(hit.get("importance") or 0.0)
    typ = str(hit.get("type") or hit.get("class") or "").lower()
    disp = _display_text(hit)
    disp_lower = disp.lower()

    if typ in _PLACE_OF_WORSHIP:
        score += 0.35
    elif (
        shrine_query
        and typ in _INARI_NEARBY_TYPES
        and any(k in disp for k in ("稲荷", "inari", "神社"))
    ):
        score += 0.2
    if typ in _UNRELIABLE_TYPES:
        score -= 1.0
    if validate_contains and validate_contains.lower() in disp_lower:
        score += 0.5
    if shrine_query and any(
        k in disp_lower for k in ("神社", "稲荷", "jinja", "inari", "shrine")
    ):
        score += 0.15

    if region_hints:
        matched = [h for h in region_hints if h in disp]
        if matched:
            score += 0.25 * min(len(matched), 3)
        else:
            score -= 0.45

    return score


def _nominatim_search(
    query: str,
    *,
    country_code: str,
    limit: int,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    params: dict[str, str | int] = {
        "q": q,
        "format": "json",
        "limit": max(1, min(limit, 10)),
        "addressdetails": 1,
    }
    cc = (country_code or "").strip().lower()
    if cc:
        params["countrycodes"] = cc

    url = f"{_nominatim_base_url()}/search?{urlencode(params)}"
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}

    _rate_limit()
    if client is not None:
        resp = client.get(url, headers=headers, timeout=30.0)
    else:
        with httpx.Client() as c:
            resp = c.get(url, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return [h for h in data if isinstance(h, dict)]


def _pick_best(
    hits: list[dict[str, Any]],
    *,
    country_code: str,
    validate_contains: str,
    shrine_query: bool,
    region_hints: set[str],
) -> dict[str, Any] | None:
    cc = (country_code or "").strip().lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for hit in hits:
        try:
            lat = float(hit["lat"])
            lon = float(hit["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if cc and not _in_bbox(lat, lon, cc):
            continue
        scored.append(
            (
                _score_hit(
                    hit,
                    validate_contains=validate_contains,
                    shrine_query=shrine_query,
                    region_hints=region_hints,
                ),
                hit,
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < -0.5:
        return None
    return best


def _format_hit(hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "display_name": _display_text(hit),
        "type": hit.get("type"),
        "class": hit.get("class"),
        "importance": hit.get("importance"),
        "osm_type": hit.get("osm_type"),
        "osm_id": hit.get("osm_id"),
    }


def geocode_place_sync(
    query: str,
    *,
    fallback_query: str = "",
    country_code: str = "",
    validate_contains: str = "",
    limit: int = 5,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Forward geocode a place name via Nominatim with optional fallback query."""
    primary = (query or "").strip()
    fallback = (fallback_query or "").strip()
    if not primary and not fallback:
        return {"ok": False, "error": "empty_query"}

    shrine_query = bool(
        _SHRINE_HINT_RE.search(primary) or _SHRINE_HINT_RE.search(fallback)
    )
    validate = (validate_contains or "").strip()
    cc = (country_code or "").strip().lower()
    region_hints = _region_hints(primary, fallback)

    attempts: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    merged_hits: list[tuple[str, dict[str, Any]]] = []
    seen_osm: set[str] = set()

    query_plan: list[tuple[str, str]] = []
    if primary:
        query_plan.append(("primary", primary))
    if fallback:
        query_plan.append(("fallback", fallback))
    for extra in _extra_queries(primary, fallback, shrine_query=shrine_query):
        query_plan.append(("extra", extra))

    for label, q in query_plan:
        try:
            hits = _nominatim_search(q, country_code=cc, limit=limit, client=client)
        except Exception as exc:
            logger.warning("nominatim search failed query=%s: %s", q[:80], exc)
            attempts.append({"query": q, "label": label, "error": str(exc)})
            continue

        attempts.append({"query": q, "label": label, "hit_count": len(hits)})
        for h in hits:
            all_candidates.append({**_format_hit(h), "query_used": q})
            osm_type = h.get("osm_type")
            osm_id = h.get("osm_id")
            if osm_type and osm_id:
                osm_key = f"{osm_type}:{osm_id}"
            else:
                osm_key = f"{h.get('lat')}:{h.get('lon')}:{h.get('display_name')}"
            if osm_key in seen_osm:
                continue
            seen_osm.add(osm_key)
            merged_hits.append((q, h))

    best = _pick_best(
        [h for _, h in merged_hits],
        country_code=cc,
        validate_contains=validate,
        shrine_query=shrine_query,
        region_hints=region_hints,
    )
    if best is not None:
        formatted = _format_hit(best)
        query_used = ""
        for q, h in merged_hits:
            if h is best:
                query_used = q
                break
        validated = True
        reason = ""
        disp = formatted["display_name"].lower()
        if validate and validate.lower() not in disp:
            validated = False
            reason = f"validate_contains '{validate}' not in display_name"

        typ = str(formatted.get("type") or "").lower()
        if shrine_query and typ in _UNRELIABLE_TYPES:
            validated = False
            reason = f"unreliable type '{typ}' for shrine-like query"

        return {
            "ok": True,
            "query_used": query_used,
            "validated": validated,
            "validation_note": reason,
            **formatted,
            "candidates": all_candidates[:10],
            "source": "nominatim",
        }

    return {
        "ok": False,
        "error": "no_suitable_hit",
        "attempts": attempts,
        "candidates": all_candidates[:10],
        "source": "nominatim",
    }


def reverse_geocode_sync(
    lat: float,
    lon: float,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Reverse geocode coordinates (sanity check)."""
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
    }
    url = f"{_nominatim_base_url()}/reverse?{urlencode(params)}"
    headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
    _rate_limit()
    if client is not None:
        resp = client.get(url, headers=headers, timeout=30.0)
    else:
        with httpx.Client() as c:
            resp = c.get(url, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        return {"ok": False, "error": "invalid_response"}
    return {
        "ok": True,
        "display_name": data.get("display_name"),
        "address": data.get("address"),
        "source": "nominatim",
    }
