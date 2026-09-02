"""
MCP geocoding: forward geocode via OpenStreetMap Nominatim.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from fastmcp import FastMCP

mcp = FastMCP("AION Geocoding")


@mcp.tool()
async def geocode_place(
    query: str,
    fallback_query: str = "",
    country_code: str = "",
    validate_contains: str = "",
    limit: int = 5,
) -> str:
    """
    Resolve a place name to WGS84 coordinates using OpenStreetMap Nominatim.

    Use for addresses, landmarks, shrines, plants — never invent lat/lon from memory.

    Args:
        query: Primary search string (e.g. "Fushimi Inari Taisha, Kyoto, Japan").
        fallback_query: Second query if the first returns no good hit (e.g. Japanese name).
        country_code: ISO 3166-1 alpha-2 filter (e.g. "jp", "it").
        validate_contains: Substring that must appear in the resolved display_name
            (e.g. prefecture name) or the result is marked validated=false.
        limit: Max Nominatim candidates (1–10).

    Returns JSON with ok, lat, lon, display_name, validated, candidates, source.
    """
    import asyncio

    from src.tools.geocode import geocode_place_sync

    result = await asyncio.to_thread(
        geocode_place_sync,
        query,
        fallback_query=fallback_query,
        country_code=country_code,
        validate_contains=validate_contains,
        limit=limit,
    )
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def reverse_geocode(lat: float, lon: float) -> str:
    """
    Reverse geocode WGS84 coordinates to a human-readable address (sanity check).

    Use after geocode_place to confirm the point matches the expected region.
    """
    import asyncio

    from src.tools.geocode import reverse_geocode_sync

    result = await asyncio.to_thread(reverse_geocode_sync, lat, lon)
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    import asyncio

    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await mcp._mcp_server.run(
                read_stream,
                write_stream,
                mcp._mcp_server.create_initialization_options(),
            )

    asyncio.run(main())
