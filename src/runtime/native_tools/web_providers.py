"""Adapter HTTP per Tavily, Brave Search API e SearXNG."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import httpx

from src.runtime.native_tools.allowlist import (
    effective_host_patterns,
    filter_result_rows_by_hosts,
    tavily_safe_include_domains,
    url_matches_hostlist,
)
from src.runtime.web_search_context import get_web_search_request_context

logger = logging.getLogger(__name__)

_WIKI_HOST_RE = re.compile(
    r"^(?P<lang>[a-z]{2,3})\.(m\.)?wikipedia\.org$", re.IGNORECASE
)
_WIKI_USER_AGENT = "AION-Agent/1.0 (+https://github.com/aion-agent; web_fetch_page)"
_SITE_OPERATOR_RE = re.compile(
    r"^\s*site:(?P<domain>[^\s/]+(?:\.[^\s/]+)*)\s*(?P<rest>.*)$",
    re.IGNORECASE,
)


def _truthy(val: Optional[str]) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def _wiki_api_headers() -> Dict[str, str]:
    """MediaWiki requires a descriptive User-Agent (403 otherwise)."""
    return {"User-Agent": _WIKI_USER_AGENT}


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


def _normalize_wiki_anchor(value: str) -> str:
    return unquote(value or "").replace("_", " ").strip().lower()


def _parse_wikipedia_url(url: str) -> Optional[Tuple[str, str, Optional[str]]]:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    m = _WIKI_HOST_RE.match(host)
    if not m:
        return None
    lang = m.group("lang").lower()
    path = unquote(parsed.path or "")
    if not path.startswith("/wiki/"):
        return None
    title = path[len("/wiki/") :].replace("_", " ").strip()
    if not title or title.lower() == "main_page":
        return None
    anchor_raw = unquote((parsed.fragment or "")).strip()
    anchor = anchor_raw if anchor_raw else None
    return lang, title, anchor


def _fetch_wikipedia_section(
    client: httpx.Client,
    *,
    lang: str,
    title: str,
    anchor: str,
    max_chars: int,
    timeout: float,
) -> Optional[str]:
    api = f"https://{lang}.wikipedia.org/w/api.php"
    target = _normalize_wiki_anchor(anchor)
    try:
        r = client.get(
            api,
            params={
                "action": "parse",
                "page": title,
                "prop": "sections",
                "format": "json",
            },
            headers=_wiki_api_headers(),
            timeout=timeout,
        )
        r.raise_for_status()
        sections = (r.json().get("parse") or {}).get("sections") or []
        section_idx: Optional[str] = None
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            candidates = (
                str(sec.get("anchor") or ""),
                str(sec.get("line") or ""),
            )
            if any(_normalize_wiki_anchor(c) == target for c in candidates if c):
                section_idx = str(sec.get("index") or "")
                break
        if not section_idx:
            logger.info(
                "wikipedia section not found title=%s anchor=%s", title[:60], anchor
            )
            return None

        r2 = client.get(
            api,
            params={
                "action": "parse",
                "page": title,
                "section": section_idx,
                "prop": "text",
                "format": "json",
            },
            headers=_wiki_api_headers(),
            timeout=timeout,
        )
        r2.raise_for_status()
        html = ((r2.json().get("parse") or {}).get("text") or {}).get("*") or ""
        if not html:
            return None
        page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        text, _ = _extract_main_text(html, url=page_url, max_chars=max_chars)
        return text.strip()[:max_chars] if text else None
    except Exception as exc:
        logger.warning(
            "wikipedia section fetch failed title=%s anchor=%s: %s",
            title[:60],
            anchor,
            exc,
        )
    return None


def _wikipedia_extract_fallback_min_chars(max_chars: int) -> int:
    """When API ``extracts`` returns fewer chars than this, fetch full HTML via parse."""
    try:
        floor = int(os.getenv("AION_WIKIPEDIA_EXTRACT_FALLBACK_MIN_CHARS", "2000"))
    except ValueError:
        floor = 2000
    return min(max_chars, max(500, floor))


def _fetch_wikipedia_parse_html(
    client: httpx.Client,
    *,
    lang: str,
    title: str,
    max_chars: int,
    timeout: float,
) -> Optional[str]:
    """Full article via MediaWiki parse + trafilatura/bs4 (tables, match lists)."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        r = client.get(
            api,
            params={
                "action": "parse",
                "page": title,
                "prop": "text",
                "format": "json",
            },
            headers=_wiki_api_headers(),
            timeout=timeout,
        )
        r.raise_for_status()
        html = ((r.json().get("parse") or {}).get("text") or {}).get("*") or ""
        if not html:
            return None
        page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
        text, _ = _extract_main_text(html, url=page_url, max_chars=max_chars)
        return text.strip()[:max_chars] if text else None
    except Exception as exc:
        logger.warning("wikipedia parse html failed title=%s: %s", title[:80], exc)
    return None


def _fetch_wikipedia_best_article(
    client: httpx.Client,
    *,
    lang: str,
    title: str,
    max_chars: int,
    timeout: float,
) -> Tuple[Optional[str], str, str, Optional[str]]:
    """Article text: API extract when sufficient, else parse+extract HTML."""
    wiki_mode = (os.getenv("AION_WIKIPEDIA_FETCH_MODE") or "article").strip().lower()
    extract = _fetch_wikipedia_extract(
        client, lang=lang, title=title, max_chars=max_chars, timeout=timeout
    )
    if wiki_mode == "intro" and extract:
        return extract, "wikipedia_api", "intro", None

    min_useful = _wikipedia_extract_fallback_min_chars(max_chars)
    html_text: Optional[str] = None
    if not extract or len(extract) < min_useful:
        html_text = _fetch_wikipedia_parse_html(
            client, lang=lang, title=title, max_chars=max_chars, timeout=timeout
        )

    if html_text and (not extract or len(html_text) > len(extract)):
        hint: Optional[str] = None
        if extract and len(extract) < min_useful:
            hint = (
                f"Wikipedia API returned only the article lead ({len(extract)} chars); "
                f"full page text fetched via MediaWiki parse ({len(html_text)} chars). "
                "For a single section, use a #anchor URL (e.g. #Matches)."
            )
        return html_text, "wikipedia_html", "article", hint

    if extract:
        source = "intro" if wiki_mode == "intro" else "article"
        return extract, "wikipedia_api", source, None

    if html_text:
        return html_text, "wikipedia_html", "article", None
    return None, "wikipedia_api", "article", None


def _fetch_wikipedia_extract(
    client: httpx.Client,
    *,
    lang: str,
    title: str,
    max_chars: int,
    timeout: float,
) -> Optional[str]:
    mode = (os.getenv("AION_WIKIPEDIA_FETCH_MODE") or "article").strip().lower()
    params: Dict[str, Any] = {
        "action": "query",
        "prop": "extracts",
        "explaintext": True,
        "redirects": 1,
        "format": "json",
        "titles": title,
    }
    if mode == "intro":
        params["exintro"] = True
    else:
        params["exchars"] = max(500, max_chars)

    api = f"https://{lang}.wikipedia.org/w/api.php"
    try:
        r = client.get(
            api, params=params, headers=_wiki_api_headers(), timeout=timeout
        )
        r.raise_for_status()
        data = r.json()
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            extract = page.get("extract")
            if isinstance(extract, str) and extract.strip():
                return extract.strip()[:max_chars]
    except Exception as exc:
        logger.warning("wikipedia API failed title=%s: %s", title[:80], exc)
    return None


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
    max_chars = int(os.getenv("AION_WEB_FETCH_MAX_CHARS", "24000"))
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

    wiki = _parse_wikipedia_url(u)
    if wiki:
        lang, title, anchor = wiki
        hint: Optional[str] = None
        with httpx.Client(
            follow_redirects=True, headers=_wiki_api_headers()
        ) as client:
            text: Optional[str] = None
            mode = "wikipedia_api"
            source = "article"
            if anchor:
                text = _fetch_wikipedia_section(
                    client,
                    lang=lang,
                    title=title,
                    anchor=anchor,
                    max_chars=max_chars,
                    timeout=timeout,
                )
                if text:
                    mode = "wikipedia_section"
                    source = anchor
            if not text:
                text, mode, source, hint = _fetch_wikipedia_best_article(
                    client,
                    lang=lang,
                    title=title,
                    max_chars=max_chars,
                    timeout=timeout,
                )
        if text:
            payload: Dict[str, Any] = {
                "url": u,
                "mode": mode,
                "source": source,
                "chars": len(text),
                "text": text,
            }
            if hint:
                payload["hint"] = hint
            return _serialize_tool_payload(payload, tool="web_fetch_page")

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
                headers={"User-Agent": "AION-Agent/1.0 (+web_fetch_page)"},
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
