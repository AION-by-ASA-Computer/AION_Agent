"""Web search/fetch bridge for deep research — AION native web tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from src.runtime.native_tools.web_providers import run_web_fetch_page, run_web_search

logger = logging.getLogger(__name__)

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_IMAGE_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.I,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)


def _parse_search_results(raw: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict) and data.get("error"):
        logger.warning("web_search error: %s", data.get("error"))
        if data.get("details"):
            logger.warning("web_search details: %s", data.get("details"))
        return []
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or "").strip()
        if not url:
            continue
        out.append(
            {
                "url": url,
                "title": row.get("title") or "",
                "snippet": row.get("snippet") or "",
                "provider": row.get("provider") or "aion",
            }
        )
    return out


async def search_web(query: str, *, max_results: int = 10) -> List[Dict[str, Any]]:
    """Run web search via AION native tools."""
    raw = await asyncio.to_thread(run_web_search, query, max_results=max_results)
    return _parse_search_results(raw)


def _extract_og_image(html: str, page_url: str) -> str:
    if not html:
        return ""
    m = _OG_IMAGE_RE.search(html) or _OG_IMAGE_RE2.search(html)
    if not m:
        return ""
    img = m.group(1).strip()
    if img.startswith("//"):
        return "https:" + img
    if img.startswith("/"):
        return urljoin(page_url, img)
    return img


def _extract_title(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    return m.group(1).strip() if m else ""


async def fetch_webpage_content(url: str, *, timeout: float = 25.0) -> Dict[str, Any]:
    """Fetch page text + optional OG image for research extraction."""
    raw = await asyncio.to_thread(run_web_fetch_page, url)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "success": False,
            "url": url,
            "content": "",
            "title": "",
            "og_image": "",
        }

    if data.get("error"):
        return {
            "success": False,
            "url": url,
            "content": "",
            "title": "",
            "og_image": "",
            "error": data.get("error"),
        }

    text = (data.get("text") or "").strip()
    og_image = ""
    title = ""

    # httpx fetch for OG meta when we only got plain text from scrapling
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            r = await client.get(
                url,
                headers={"User-Agent": "AION-Agent/1.0 (+deep_research)"},
            )
            if r.status_code < 400:
                html = r.text[:500_000]
                og_image = _extract_og_image(html, url)
                title = _extract_title(html)
    except Exception as e:
        logger.debug("OG fetch failed for %s: %s", url, e)

    if not title:
        try:
            title = urlparse(url).netloc
        except Exception:
            title = url

    return {
        "success": bool(text),
        "url": url,
        "content": text,
        "title": title,
        "og_image": og_image,
    }
