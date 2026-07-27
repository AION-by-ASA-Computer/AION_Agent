"""Adapter HTTP per Tavily, Brave Search API e SearXNG."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
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

_FETCH_USER_AGENT = "AION-Agent/1.0 (+https://github.com/aion-agent; web_fetch_page)"
_SITE_OPERATOR_RE = re.compile(
    r"^\s*site:(?P<domain>[^\s/]+(?:\.[^\s/]+)*)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


def _truthy(val: Optional[str]) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def _normalize_web_search_query(query: str) -> Tuple[str, List[str], Optional[str]]:
    """Parse ``site:domain`` operator into a clean query + domain hints.

    Search APIs differ: Tavily ignores or mishandles ``site:`` in the query string,
    so we strip it and apply domain restriction via ``include_domains`` / post-filter.
    """
    raw = (query or "").strip()
    m = _SITE_OPERATOR_RE.match(raw)
    if not m:
        return raw, [], None
    from src.runtime.native_tools.allowlist import normalize_hostname

    domain = normalize_hostname(m.group("domain"))
    rest = (m.group("rest") or "").strip().strip("\\/").strip()
    if not domain:
        return raw, [], "site_operator_domain_invalid"
    if not rest:
        return raw, [domain], "site_operator_missing_terms"
    return rest, [domain], None


def _tool_result_format() -> str:
    return (os.getenv("AION_TOOL_RESULT_FORMAT") or "toon").strip().lower()


def _serialize_tool_payload(data: Dict[str, Any], *, tool: str) -> str:
    if _tool_result_format() == "json":
        return json.dumps(data, ensure_ascii=False)
    from src.runtime.toon_encode import format_web_fetch_toon, format_web_search_toon

    if tool == "web_search":
        return format_web_search_toon(data)
    if tool == "web_fetch_page":
        return format_web_fetch_toon(data)
    return json.dumps(data, ensure_ascii=False)


def _enabled_providers() -> List[str]:
    order: List[str] = []
    default = (
        (os.getenv("AION_WEB_SEARCH_DEFAULT_PROVIDER") or "tavily").strip().lower()
    )
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


def web_search_availability() -> Dict[str, Any]:
    """Which search providers are enabled (deep research diagnostics)."""
    enabled = [p for p in ("tavily", "brave", "searxng") if _provider_on(p)]
    return {
        "any_enabled": bool(enabled),
        "enabled": enabled,
        "default_provider": (os.getenv("AION_WEB_SEARCH_DEFAULT_PROVIDER") or "tavily")
        .strip()
        .lower(),
    }


def _provider_on(name: str) -> bool:
    env = f"AION_WEB_SEARCH_{name.upper()}_ENABLED"
    return _truthy(os.getenv(env, "0"))


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
        "search_depth": depth
        if depth in ("basic", "advanced", "fast", "ultra-fast")
        else "basic",
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
    """Esegue ricerca con fallback tra provider abilitati."""
    if not query or not str(query).strip():
        return _serialize_tool_payload(
            {"error": "query vuota", "results": []}, tool="web_search"
        )
    search_q, site_domains, site_err = _normalize_web_search_query(query)
    if site_err == "site_operator_missing_terms":
        return _serialize_tool_payload(
            {
                "error": "site_operator_missing_terms",
                "message": (
                    "Add search terms after site:domain "
                    "(e.g. site:wikipedia.org 2026 World Cup group A results)."
                ),
                "query": query,
                "results": [],
            },
            tool="web_search",
        )
    if site_err == "site_operator_domain_invalid":
        return _serialize_tool_payload(
            {
                "error": "site_operator_domain_invalid",
                "query": query,
                "results": [],
            },
            tool="web_search",
        )

    ctx = get_web_search_request_context()
    patterns, perr = effective_host_patterns(list(ctx.restrict_hosts))
    if perr:
        return _serialize_tool_payload(
            {
                "error": "host_not_in_org_allowlist",
                "detail": perr,
                "query": query,
                "results": [],
            },
            tool="web_search",
        )
    tavily_domains = tavily_safe_include_domains(patterns) if patterns else []
    if site_domains:
        tavily_domains = list(
            dict.fromkeys(site_domains + tavily_domains)
        )[:300]

    max_r = max_results or int(os.getenv("AION_WEB_SEARCH_MAX_RESULTS", "8"))
    max_r = max(1, min(max_r, 20))
    timeout = float(os.getenv("AION_WEB_SEARCH_TIMEOUT_SEC", "30"))
    lang = (language or os.getenv("AION_WEB_SEARCH_LANGUAGE") or "").strip()

    order = _enabled_providers()
    enabled = [p for p in order if _provider_on(p)]
    if not enabled:
        return _serialize_tool_payload(
            {
                "query": query,
                "error": "web_search_disabled",
                "message": (
                    "Nessun provider web_search abilitato. Imposta "
                    "AION_WEB_SEARCH_TAVILY_ENABLED=1 (e AION_TAVILY_API_KEY) "
                    "oppure abilita Brave/SearXNG in .env."
                ),
                "results": [],
            },
            tool="web_search",
        )

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
                        search_q,
                        max_r,
                        timeout,
                        include_domains=tavily_domains or None,
                    )
                elif prov == "brave":
                    rows = _search_brave(client, search_q, max_r, timeout)
                elif prov == "searxng":
                    rows = _search_searxng(client, search_q, max_r, timeout)
                else:
                    continue
                if lang:
                    pass
                if site_domains:
                    rows = filter_result_rows_by_hosts(rows, site_domains)
                if patterns:
                    rows = filter_result_rows_by_hosts(rows, patterns)
                if rows:
                    return _serialize_tool_payload(
                        {"query": query, "provider_used": prov, "results": rows},
                        tool="web_search",
                    )
                errors.append(f"{prov}: zero risultati")
            except Exception as e:
                logger.warning("web_search provider %s failed: %s", prov, e)
                errors.append(f"{prov}: {e}")
    return _serialize_tool_payload(
        {
            "query": query,
            "error": "all providers failed or are disabled",
            "details": errors,
            "results": [],
        },
        tool="web_search",
    )


def _url_path_looks_pdf(url: str) -> bool:
    try:
        return urlparse(url).path.lower().endswith(".pdf")
    except Exception:
        return False


def _pdf_not_text_extractable_payload(url: str) -> str:
    return _serialize_tool_payload(
        {
            "error": "pdf_not_text_extractable",
            "url": url,
            "text": "",
            "hint": (
                "web_fetch_page does not extract text from PDFs. Cite the URL "
                "(sources from web_search) or an OCR/document tool if available."
            ),
        },
        tool="web_fetch_page",
    )


def _strip_html_simple(html: str, max_chars: int) -> str:
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_chars]


def _extract_main_text(html: str, *, url: str, max_chars: int) -> Tuple[str, str]:
    """Return (text, mode) using best available extractor."""
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
            output_format="txt",
        )
        if text and text.strip():
            return text.strip()[:max_chars], "trafilatura"
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("trafilatura extract failed for %s: %s", url, exc)

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.body
        text = (article or soup).get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if text.strip():
            return text.strip()[:max_chars], "beautifulsoup"
    except Exception as exc:
        logger.debug("beautifulsoup extract failed for %s: %s", url, exc)

    return _strip_html_simple(html, max_chars), "html_strip"


def _web_fetch_max_chars() -> int:
    """Page extract cap before serialization. Higher when tool offload stores full text on disk."""
    try:
        base = max(2000, int(os.getenv("AION_WEB_FETCH_MAX_CHARS", "24000")))
    except ValueError:
        base = 24000
    try:
        from src.runtime.tool_offload import offload_enabled

        if not offload_enabled():
            return base
    except Exception:
        return base
    raw = (os.getenv("AION_WEB_FETCH_OFFLOAD_MAX_CHARS") or "").strip()
    if raw:
        try:
            return max(base, int(raw))
        except ValueError:
            pass
    try:
        max_bytes = max(50_000, int(os.getenv("AION_WEB_FETCH_MAX_BYTES", "1500000")))
    except ValueError:
        max_bytes = 1_500_000
    return max(base, min(max_bytes // 2, 250_000))


def run_web_fetch_page(url: str, *, prefer_stealth: bool = False) -> str:
    """Scarica una singola pagina e restituisce testo (TOON o JSON)."""
    if not url or not str(url).strip().lower().startswith(("http://", "https://")):
        return _serialize_tool_payload(
            {"error": "URL http(s) richiesto", "text": ""}, tool="web_fetch_page"
        )
    u = str(url).strip()
    ctx = get_web_search_request_context()
    patterns, perr = effective_host_patterns(list(ctx.restrict_hosts))
    if perr:
        return _serialize_tool_payload(
            {
                "error": "host_not_in_org_allowlist",
                "detail": perr,
                "url": u,
                "text": "",
            },
            tool="web_fetch_page",
        )
    if patterns and not url_matches_hostlist(u, patterns):
        return _serialize_tool_payload(
            {"error": "url_not_in_allowlist", "url": u, "text": ""},
            tool="web_fetch_page",
        )
    timeout = float(os.getenv("AION_WEB_FETCH_TIMEOUT_SEC", "25"))
    max_bytes = int(os.getenv("AION_WEB_FETCH_MAX_BYTES", "1500000"))
    max_chars = _web_fetch_max_chars()
    allow = (os.getenv("AION_WEB_FETCH_ALLOWLIST_REGEX") or "").strip()
    if allow:
        try:
            if not re.search(allow, u):
                return _serialize_tool_payload(
                    {
                        "error": "URL non ammesso da AION_WEB_FETCH_ALLOWLIST_REGEX",
                        "url": u,
                    },
                    tool="web_fetch_page",
                )
        except re.error as e:
            return _serialize_tool_payload(
                {"error": f"regex allowlist invalida: {e}", "url": u},
                tool="web_fetch_page",
            )

    if _url_path_looks_pdf(u):
        return _pdf_not_text_extractable_payload(u)

    stealth = prefer_stealth and _truthy(
        os.getenv("AION_SCRAPLING_STEALTH_ENABLED", "0")
    )

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
            text, mode = _extract_main_text(html, url=u, max_chars=max_chars)
            return _serialize_tool_payload(
                {"url": u, "mode": mode, "chars": len(text), "text": text},
                tool="web_fetch_page",
            )
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
            text, mode = _extract_main_text(html, url=u, max_chars=max_chars)
            return _serialize_tool_payload(
                {"url": u, "mode": f"scrapling_stealthy+{mode}", "chars": len(text), "text": text},
                tool="web_fetch_page",
            )
        except Exception as e:
            logger.warning("scrapling StealthyFetcher failed for %s: %s", u, e)

    try:
        with httpx.Client(follow_redirects=True) as client:
            r = client.get(
                u,
                timeout=timeout,
                headers={"User-Agent": _FETCH_USER_AGENT},
            )
            r.raise_for_status()
            body = r.content[:max_bytes]
            ctype = (r.headers.get("content-type") or "").lower()
            if "application/pdf" in ctype:
                return _pdf_not_text_extractable_payload(u)
            if len(body) >= 5 and body[:5] == b"%PDF-":
                return _pdf_not_text_extractable_payload(u)
            path_lower = u.lower().split("?", 1)[0]
            if "html" in ctype or path_lower.endswith((".htm", ".html")):
                html = body.decode("utf-8", errors="replace")
                text, mode = _extract_main_text(html, url=u, max_chars=max_chars)
            else:
                text = body.decode("utf-8", errors="replace")[:max_chars]
                mode = "httpx_raw"
            return _serialize_tool_payload(
                {"url": u, "mode": mode, "chars": len(text), "text": text},
                tool="web_fetch_page",
            )
    except Exception as e:
        return _serialize_tool_payload(
            {"error": str(e), "url": u, "text": ""}, tool="web_fetch_page"
        )
