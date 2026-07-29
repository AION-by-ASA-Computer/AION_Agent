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


def _strip_toon_fence(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```toon"):
        text = re.sub(r"^```toon\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_toon_scalar(value: str) -> str:
    v = (value or "").strip()
    if v.startswith('"') and v.endswith('"'):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v[1:-1]
    return v


def _parse_web_fetch_payload(raw: str) -> Optional[Dict[str, Any]]:
    """Parse web_fetch_page JSON or TOON payload for deep research."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```toon"):
        text = _strip_toon_fence(text)
        out: Dict[str, Any] = {}
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if re.match(r"^text:\s*\|\s*$", line.strip()):
                i += 1
                block: List[str] = []
                while i < len(lines):
                    if lines[i].startswith("  "):
                        block.append(lines[i][2:])
                        i += 1
                        continue
                    break
                out["text"] = "\n".join(block)
                continue
            kv = re.match(r"^([a-zA-Z_][\w]*):\s*(.*)$", line)
            if kv:
                key, val = kv.group(1), kv.group(2)
                if key == "text" and val == "|":
                    i += 1
                    block = []
                    while i < len(lines):
                        if lines[i].startswith("  "):
                            block.append(lines[i][2:])
                            i += 1
                            continue
                        break
                    out["text"] = "\n".join(block)
                    continue
                out[key] = _parse_toon_scalar(val)
            i += 1
        return out or None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_web_search_payload(raw: str) -> Optional[Dict[str, Any]]:
    """Parse web_search JSON or TOON payload for deep research."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```toon"):
        from src.runtime.toon_encode import parse_web_search_toon

        return parse_web_search_toon(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _rows_from_search_payload(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if data.get("error"):
        logger.warning("web_search error: %s", data.get("error"))
        if data.get("details"):
            logger.warning("web_search details: %s", data.get("details"))
        if data.get("message"):
            logger.warning("web_search message: %s", data.get("message"))
        return []
    rows = data.get("results")
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
                "provider": row.get("provider") or data.get("provider_used") or "aion",
            }
        )
    return out


def _parse_search_results(raw: str) -> List[Dict[str, Any]]:
    return _rows_from_search_payload(_parse_web_search_payload(raw))


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
    data = _parse_web_fetch_payload(raw)
    if not isinstance(data, dict):
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
