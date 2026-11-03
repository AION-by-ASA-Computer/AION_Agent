"""Deprecazione di una singola route (regola in ``docs/api-and-runtime/rest-api.md``).

    @router.get("/old", **deprecated_route(date(2027, 3, 1), successor="/v1/new"))

La route compare in OpenAPI come ``deprecated`` con ``x-sunset`` (letto da
``src/api/contract_diff.py``: dopo il Sunset la route può essere rimossa senza
far fallire il controllo del contratto) e ogni risposta riceve gli header
``Deprecation``, ``Sunset`` e, se indicato, ``Link`` verso il successore.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from email.utils import format_datetime
from typing import Any, Dict, Optional

from fastapi import Depends, Response


def sunset_http_date(sunset: date) -> str:
    """``date`` → HTTP-date (RFC 9110), mezzanotte UTC."""
    return format_datetime(
        datetime.combine(sunset, time(0), tzinfo=timezone.utc), usegmt=True
    )


def deprecation_headers(
    sunset: date, successor: Optional[str] = None
) -> Dict[str, str]:
    headers = {"Deprecation": "true", "Sunset": sunset_http_date(sunset)}
    if successor:
        headers["Link"] = f'<{successor}>; rel="successor-version"'
    return headers


def deprecated_route(sunset: date, successor: Optional[str] = None) -> Dict[str, Any]:
    """Argomenti per il decoratore della route (``**deprecated_route(...)``).

    Gli header sono impostati con una dipendenza: valgono per gli handler che
    restituiscono dati, non per quelli che costruiscono una ``Response``.
    """
    headers = deprecation_headers(sunset, successor)

    def _set_headers(response: Response) -> None:
        response.headers.update(headers)

    extra: Dict[str, Any] = {"x-sunset": sunset.isoformat()}
    if successor:
        extra["x-successor"] = successor
    return {
        "deprecated": True,
        "openapi_extra": extra,
        "dependencies": [Depends(_set_headers)],
    }
