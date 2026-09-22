"""
MCP geocoding: forward geocode via OpenStreetMap Nominatim.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

from src.tools.geocode import geocode_place_sync, reverse_geocode_sync

mcp = FastMCP("AION Geocoding")


@mcp.tool()
def geocode_place(
    query: str,
    fallback_query: str = "",
    country_code: str = "",
    validate_contains: str = "",
    limit: int = 5,
) -> str:
    """
    Resolve a place name to WGS84 coordinates using OpenStreetMap Nominatim.

    Use for addresses, landmarks, shrines, plants - never invent lat/lon from memory.

    Args:
        query: Primary search string (e.g. "Fushimi Inari Taisha, Kyoto, Japan").
        fallback_query: Second query if the first returns no good hit (e.g. Japanese name).
        country_code: ISO 3166-1 alpha-2 filter (e.g. "jp", "it").
        validate_contains: Substring that must appear in the resolved display_name
            (e.g. prefecture name) or the result is marked validated=false.
        limit: Max Nominatim candidates (1-10).

    Returns JSON with ok, lat, lon, display_name, validated, candidates, source.
    """
    result = geocode_place_sync(
        query,
        fallback_query=fallback_query,
        country_code=country_code,
        validate_contains=validate_contains,
        limit=limit,
    )
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def reverse_geocode(lat: float, lon: float) -> str:
    """
    Reverse geocode WGS84 coordinates to a human-readable address (sanity check).

    Use after geocode_place to confirm the point matches the expected region.
    """
    result = reverse_geocode_sync(lat, lon)
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
