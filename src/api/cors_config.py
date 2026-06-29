"""CORS middleware settings from environment."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("aion.api.cors")


@dataclass(frozen=True)
class CorsSettings:
    allow_origins: List[str]
    allow_origin_regex: Optional[str]
    allow_credentials: bool = True
    allow_methods: List[str] = None  # type: ignore[assignment]
    allow_headers: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allow_methods", self.allow_methods or ["*"])
        object.__setattr__(self, "allow_headers", self.allow_headers or ["*"])


def _truthy(val: str) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def _default_restricted_origins() -> List[str]:
    origins: List[str] = [
        "http://localhost:8003",
        "http://127.0.0.1:8003",
        "http://localhost:3870",
        "http://127.0.0.1:3870",
    ]
    for env_key in ("AION_PUBLIC_API_URL", "NEXT_PUBLIC_AION_API_URL"):
        raw = (os.getenv(env_key) or "").strip().rstrip("/")
        if raw.startswith("http"):
            origin = raw.replace("/api", "").rstrip("/")
            if origin not in origins:
                origins.append(origin)
    admin = (
        os.getenv("AION_ADMIN_UI_URL")
        or os.getenv("NEXT_PUBLIC_AION_ADMIN_UI_URL")
        or ""
    ).strip()
    if admin.startswith("http") and admin.rstrip("/") not in origins:
        origins.append(admin.rstrip("/"))
    return origins


def resolve_cors_settings() -> CorsSettings:
    """
    Explicit origin list by default. Wildcard (regex) only in dev or with
    AION_CORS_ALLOW_WILDCARD=1.
    """
    cors_raw = (os.getenv("AION_CORS_ORIGINS") or "").strip()
    env = (os.getenv("AION_ENV") or "dev").strip().lower()
    allow_wildcard_flag = _truthy(os.getenv("AION_CORS_ALLOW_WILDCARD", ""))

    if cors_raw and cors_raw != "*":
        origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        return CorsSettings(allow_origins=origins, allow_origin_regex=None)

    if cors_raw == "*":
        if env == "prod" and not allow_wildcard_flag:
            logger.warning(
                "AION_CORS_ORIGINS=* in production without AION_CORS_ALLOW_WILDCARD=1; "
                "using restricted default origins"
            )
            return CorsSettings(
                allow_origins=_default_restricted_origins(), allow_origin_regex=None
            )
        if allow_wildcard_flag or env == "dev":
            logger.warning(
                "CORS wildcard active (allow_origin_regex=.*). "
                "Set explicit AION_CORS_ORIGINS in production."
            )
            return CorsSettings(allow_origins=[], allow_origin_regex=".*")

    return CorsSettings(
        allow_origins=_default_restricted_origins(), allow_origin_regex=None
    )
