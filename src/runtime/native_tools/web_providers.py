"""Adapter HTTP per Tavily, Brave Search API e SearXNG."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from src.runtime.native_tools.allowlist import (
    effective_host_patterns,
    filter_result_rows_by_hosts,
    tavily_safe_include_domains,
    url_matches_hostlist,
)
from src.runtime.web_search_context import get_web_search_request_context

logger = logging.getLogger(__name__)


def _truthy(val: Optional[str]) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def _enabled_providers() -> List[str]:
    order: List[str] = []
    default = (os.getenv("AION_WEB_SEARCH_DEFAULT_PROVIDER") or "tavily").strip().lower()
    fb_raw = (os.getenv("AION_WEB_SEARCH_FALLBACK_ORDER") or "").strip()
    fallback = [p.strip().lower() for p in fb_raw.split(",") if p.strip()]
    seen = set()
    for p in [default] + fallback:
        if p not in ("tavily", "brave", "searxng"):
            continue
        if p in seen:
            continue
        seen.add(p)
        order.append(p)
    if not order:
        order = ["tavily", "brave", "searxng"]
    return order


def _provider_on(name: str) -> bool:
    env = f"AION_WEB_SEARCH_{name.upper()}_ENABLED"
    return _truthy(os.getenv(env, "0"))


def web_search_availability() -> Dict[str, Any]:
    """Which search providers are enabled (deep research diagnostics)."""
    enabled = [p for p in ("tavily", "brave", "searxng") if _provider_on(p)]
    return {
        "any_enabled": bool(enabled),
        "enabled": enabled,
        "default_provider": (os.getenv("AION_WEB_SEARCH_DEFAULT_PROVIDER") or "tavily").strip().lower(),
    }


def _search_tavily(
    client: httpx.Client,
    query: str,
    max_results: int,
    timeout: float,
    include_domains: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    key = (os.getenv("AION_TAVILY_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("AION_TAVILY_API_KEY missing")
    depth = (os.getenv("AION_TAVILY_SEARCH_DEPTH") or "basic").strip()
    body: Dict[str, Any] = {
        "api_key": key,
        "query": query,
        "max_results": max(1, min(max_results, 20)),
        "search_depth": depth if depth in ("basic", "advanced", "fast", "ultra-fast") else "basic",
    }
    if include_domains:
        body["include_domains"] = include_domains
    r = client.post("https://api.tavily.com/search", json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    out: List[Dict[str, Any]] = []
    for row in data.get("results") or []:
        out.append(
            {
                "title": row.get("title") or "",
                "url": row.get("url") or "",
                "snippet": (row.get("content") or row.get("snippet") or "")[:4000],
                "provider": "tavily",
            }
        )
    return out


def _search_brave(
    client: httpx.Client, query: str, max_results: int, timeout: float
) -> List[Dict[str, Any]]:
    key = (os.getenv("AION_BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("AION_BRAVE_SEARCH_API_KEY missing")
    count = max(1, min(max_results, 20))
    r = client.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    web = (data.get("web") or {}) if isinstance(data, dict) else {}
    rows = web.get("results") or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "title": row.get("title") or "",
                "url": row.get("url") or "",
                "snippet": (row.get("description") or "")[:4000],
                "provider": "brave",
            }
        )
    return out


def _search_searxng(
    client: httpx.Client, query: str, max_results: int, timeout: float
) -> List[Dict[str, Any]]:
    base = (os.getenv("AION_SEARXNG_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise RuntimeError("AION_SEARXNG_BASE_URL missing")
    r = client.get(
        f"{base}/search",
        params={"q": query, "format": "json", "pageno": 1},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    rows = data.get("results") or []
    out: List[Dict[str, Any]] = []
    for row in rows[:max_results]:
        out.append(
            {
                "title": row.get("title") or "",
                "url": row.get("url") or "",
                "snippet": (row.get("content") or "")[:4000],
                "provider": "searxng",
            }
        )
    return out


def run_web_search(
    query: str,
    *,
    max_results: Optional[int] = None,
    language: Optional[str] = None,
) -> str:
    """Esegue ricerca con fallback tra provider abilitati. Ritorna JSON string."""
    if not query or not str(query).strip():
        return json.dumps({"error": "query vuota", "results": []}, ensure_ascii=False)
    ctx = get_web_search_request_context()
    patterns, perr = effective_host_patterns(list(ctx.restrict_hosts))
    if perr:
        code = "host_not_in_org_allowlist"
        return json.dumps(
            {"error": code, "detail": perr, "query": query, "results": []},
            ensure_ascii=False,
        )
    tavily_domains = tavily_safe_include_domains(patterns) if patterns else []

    max_r = max_results or int(os.getenv("AION_WEB_SEARCH_MAX_RESULTS", "8"))
    max_r = max(1, min(max_r, 20))
    timeout = float(os.getenv("AION_WEB_SEARCH_TIMEOUT_SEC", "30"))
    lang = (language or os.getenv("AION_WEB_SEARCH_LANGUAGE") or "").strip()

    order = _enabled_providers()
    errors: List[str] = []
    with httpx.Client(follow_redirects=True) as client:
        for prov in order:
            if not _provider_on(prov):
                errors.append(f"{prov}: disabled")
                continue
            try:
                if prov == "tavily":
                    rows = _search_tavily(
                        client,
                        query.strip(),
                        max_r,
                        timeout,
                        include_domains=tavily_domains or None,
                    )
                elif prov == "brave":
                    rows = _search_brave(client, query.strip(), max_r, timeout)
                elif prov == "searxng":
                    rows = _search_searxng(client, query.strip(), max_r, timeout)
                else:
                    continue
                if lang:
                    # filtro leggero: molti motori già rispettano lang via query; niente post-filter aggressivo
                    pass
                if patterns:
                    rows = filter_result_rows_by_hosts(rows, patterns)
                if rows:
                    return json.dumps(
                        {"query": query, "provider_used": prov, "results": rows},
                        ensure_ascii=False,
                    )
                errors.append(f"{prov}: zero risultati")
            except Exception as e:
                logger.warning("web_search provider %s failed: %s", prov, e)
                errors.append(f"{prov}: {e}")
    return json.dumps(
        {"query": query, "error": "all providers failed or are disabled", "details": errors, "results": []},
        ensure_ascii=False,
    )


def _url_path_looks_pdf(url: str) -> bool:
    try:
        return urlparse(url).path.lower().endswith(".pdf")
    except Exception:
        return False


def _pdf_not_text_extractable_payload(url: str) -> str:
    return json.dumps(
        {
            "error": "pdf_not_text_extractable",
            "url": url,
            "text": "",
            "hint": (
                "web_fetch_page does not extract text from PDFs. Cite the URL (sources from web_search) "
                "or an OCR/document tool if available in the profile."
            ),
        },
        ensure_ascii=False,
    )


def _strip_html_simple(html: str, max_chars: int) -> str:
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_chars]


def run_web_fetch_page(url: str, *, prefer_stealth: bool = False) -> str:
    """Scarica una singola pagina e restituisce testo (JSON)."""
    if not url or not str(url).strip().lower().startswith(("http://", "https://")):
        return json.dumps({"error": "URL http(s) richiesto", "text": ""}, ensure_ascii=False)
    u = str(url).strip()
    ctx = get_web_search_request_context()
    patterns, perr = effective_host_patterns(list(ctx.restrict_hosts))
    if perr:
        return json.dumps(
            {
                "error": "host_not_in_org_allowlist",
                "detail": perr,
                "url": u,
                "text": "",
            },
            ensure_ascii=False,
        )
    if patterns and not url_matches_hostlist(u, patterns):
        return json.dumps(
            {"error": "url_not_in_allowlist", "url": u, "text": ""},
            ensure_ascii=False,
        )
    timeout = float(os.getenv("AION_WEB_FETCH_TIMEOUT_SEC", "25"))
    max_bytes = int(os.getenv("AION_WEB_FETCH_MAX_BYTES", "2000000"))
    max_chars = int(os.getenv("AION_WEB_FETCH_MAX_CHARS", "120000"))
    allow = (os.getenv("AION_WEB_FETCH_ALLOWLIST_REGEX") or "").strip()
    if allow:
        try:
            if not re.search(allow, u):
                return json.dumps(
                    {"error": f"URL non ammesso da AION_WEB_FETCH_ALLOWLIST_REGEX", "url": u},
                    ensure_ascii=False,
                )
        except re.error as e:
            return json.dumps({"error": f"regex allowlist invalida: {e}", "url": u}, ensure_ascii=False)

    if _url_path_looks_pdf(u):
        return _pdf_not_text_extractable_payload(u)

    stealth = prefer_stealth and _truthy(os.getenv("AION_SCRAPLING_STEALTH_ENABLED", "0"))

    # 1) Scrapling Fetcher (richiede scrapling[fetchers])
    try:
        from scrapling.fetchers import Fetcher  # type: ignore
    except ImportError:
        Fetcher = None  # type: ignore

    if Fetcher is not None and not stealth:
        try:
            page = Fetcher.get(u, timeout=timeout)
            html = getattr(page, "html", None) or getattr(page, "text", None)
            if html is None:
                html = str(page)
            if isinstance(html, bytes):
                if len(html) >= 5 and html[:5] == b"%PDF-":
                    return _pdf_not_text_extractable_payload(u)
                html = html.decode("utf-8", errors="replace")
            elif isinstance(html, str) and html.lstrip().startswith("%PDF-"):
                return _pdf_not_text_extractable_payload(u)
            text = _strip_html_simple(html, max_chars)
            return json.dumps({"url": u, "mode": "scrapling_fetcher", "text": text}, ensure_ascii=False)
        except Exception as e:
            logger.warning("scrapling Fetcher failed for %s: %s", u, e)

    if stealth:
        try:
            from scrapling.fetchers import StealthyFetcher  # type: ignore

            page = StealthyFetcher.fetch(u, headless=True, timeout=int(timeout))
            html = getattr(page, "html", None) or str(page)
            if isinstance(html, bytes):
                if len(html) >= 5 and html[:5] == b"%PDF-":
                    return _pdf_not_text_extractable_payload(u)
                html = html.decode("utf-8", errors="replace")
            elif isinstance(html, str) and html.lstrip().startswith("%PDF-"):
                return _pdf_not_text_extractable_payload(u)
            text = _strip_html_simple(html, max_chars)
            return json.dumps({"url": u, "mode": "scrapling_stealthy", "text": text}, ensure_ascii=False)
        except Exception as e:
            logger.warning("scrapling StealthyFetcher failed for %s: %s", u, e)

    # 2) httpx fallback
    try:
        with httpx.Client(follow_redirects=True) as client:
            r = client.get(u, timeout=timeout, headers={"User-Agent": "AION-Agent/1.0 (+web_fetch_page)"})
            r.raise_for_status()
            body = r.content[:max_bytes]
            ctype = (r.headers.get("content-type") or "").lower()
            if "application/pdf" in ctype:
                return _pdf_not_text_extractable_payload(u)
            if len(body) >= 5 and body[:5] == b"%PDF-":
                return _pdf_not_text_extractable_payload(u)
            path_lower = u.lower().split("?", 1)[0]
            if "html" in ctype or path_lower.endswith((".htm", ".html")):
                text = _strip_html_simple(body.decode("utf-8", errors="replace"), max_chars)
            else:
                text = body.decode("utf-8", errors="replace")[:max_chars]
            return json.dumps({"url": u, "mode": "httpx", "text": text}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "url": u, "text": ""}, ensure_ascii=False)
