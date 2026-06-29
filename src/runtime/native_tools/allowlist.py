"""Allowlist host per web_search / web_fetch_page (admin + utente)."""

from __future__ import annotations

import os
from fnmatch import fnmatch
from typing import List, Optional, Tuple
from urllib.parse import urlparse


def _truthy(val: Optional[str]) -> bool:
    if val is None:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def parse_hosts_csv(raw: Optional[str]) -> List[str]:
    if not raw or not str(raw).strip():
        return []
    out: List[str] = []
    for part in str(raw).replace(";", ",").split(","):
        s = part.strip().lower()
        if s:
            out.append(s)
    return out


def normalize_hostname(host: str) -> str:
    h = (host or "").strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def hostname_from_url(url: str) -> Optional[str]:
    try:
        u = urlparse(url)
        if not u.hostname:
            return None
        return normalize_hostname(u.hostname)
    except Exception:
        return None


def host_matches_pattern(host: str, pattern: str) -> bool:
    """host e pattern: lowercase consigliato; pattern può essere *.esempio.it o glob."""
    h = normalize_hostname(host)
    p = (pattern or "").strip().lower()
    if not h or not p:
        return False
    if p.startswith("*."):
        suffix = p[2:]
        return h == suffix or h.endswith("." + suffix)
    if "*" in p or "?" in p:
        return fnmatch(h, p)
    return h == p or h.endswith("." + p)


def url_matches_hostlist(url: str, patterns: List[str]) -> bool:
    h = hostname_from_url(url)
    if not h:
        return False
    for pat in patterns:
        if host_matches_pattern(h, pat):
            return True
    return False


def filter_result_rows_by_hosts(rows: List[dict], patterns: List[str]) -> List[dict]:
    if not patterns:
        return rows
    return [r for r in rows if url_matches_hostlist(str(r.get("url") or ""), patterns)]


def tavily_safe_include_domains(patterns: List[str]) -> List[str]:
    """Solo domini senza wildcard per include_domains Tavily."""
    out: List[str] = []
    for p in patterns:
        p = p.strip().lower().lstrip("www.")
        if not p or "*" in p or "?" in p:
            continue
        if p not in out:
            out.append(p)
    return out[:300]


def admin_allowlist_from_env() -> List[str]:
    return parse_hosts_csv(os.getenv("AION_WEB_SEARCH_ALLOWED_HOSTS"))


def enforce_global_allowlist() -> bool:
    return _truthy(os.getenv("AION_WEB_SEARCH_ENFORCE_GLOBAL_ALLOWLIST", "0"))


def validate_user_hosts_subset(
    user_hosts: List[str], admin_patterns: List[str]
) -> Optional[str]:
    """Ogni voce utente deve essere coperta dall'allowlist admin (hostname di prova)."""
    if not admin_patterns or not user_hosts:
        return None
    for raw in user_hosts:
        raw = str(raw).strip().lower()
        if not raw:
            continue
        samples: List[str] = []
        if raw.startswith("*."):
            suffix = raw[2:]
            samples = [normalize_hostname(suffix), normalize_hostname(f"a.{suffix}")]
        elif "*" in raw or "?" in raw:
            samples = [normalize_hostname(raw.replace("*", "z").replace("?", "z"))]
        else:
            samples = [normalize_hostname(raw)]
        for s in samples:
            if not any(host_matches_pattern(s, a) for a in admin_patterns):
                return f"host_not_in_org_allowlist:{raw}"
    return None


def effective_host_patterns(
    user_restrict: Optional[List[str]],
) -> Tuple[List[str], Optional[str]]:
    """
    Ritorna (patterns_per_filtro_URL, errore).
    Con enforce+admin e lista utente validata, filtrare solo per user (sottoinsieme).
    """
    admin = admin_allowlist_from_env()
    enforce = enforce_global_allowlist()
    user = [str(x).strip() for x in (user_restrict or []) if str(x).strip()]
    user = [x.lower() for x in user]

    if enforce and admin:
        if user:
            err = validate_user_hosts_subset(user, admin)
            if err:
                return [], err
            return user, None
        return admin, None

    if user:
        return user, None
    return [], None
