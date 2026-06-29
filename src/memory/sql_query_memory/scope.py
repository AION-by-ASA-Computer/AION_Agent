"""Resolve tenant scope and user_scope_key for SQL QueryMemory."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

SHARED_SCOPE_KEY = "__shared__"


@dataclass
class ScopeContext:
    tenant_id: str
    user_id: str
    profile_slug: Optional[str]
    project_scope_mode: str  # inherit | shared | per_user


def default_tenant_id() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


def env_default_scope() -> str:
    raw = (os.getenv("AION_SQL_QM_DEFAULT_SCOPE") or "per_user").strip().lower()
    return raw if raw in ("shared", "per_user") else "per_user"


def effective_scope(project_scope_mode: str, tenant_sql_default_scope: str) -> str:
    mode = (project_scope_mode or "inherit").strip().lower()
    if mode in ("shared", "per_user"):
        return mode
    base = (tenant_sql_default_scope or env_default_scope()).strip().lower()
    return base if base in ("shared", "per_user") else "per_user"


def user_scope_key(scope: str, user_id: str) -> str:
    if scope == "shared":
        return SHARED_SCOPE_KEY
    return (user_id or "default").strip() or "default"


def datasource_key_from_env(profile_slug: Optional[str] = None) -> str:
    url = (os.getenv("POSTGRES_URL") or os.getenv("AION_POSTGRES_URL") or "").strip()
    if not url:
        return f"default:{profile_slug or 'postgres'}"
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        host = p.hostname or "localhost"
        db = (p.path or "/").lstrip("/").split("?")[0] or "postgres"
        prof = (profile_slug or "").strip()
        base = f"{host}:{db}"
        return f"{base}:{prof}" if prof else base
    except Exception:
        return f"default:{profile_slug or 'postgres'}"
