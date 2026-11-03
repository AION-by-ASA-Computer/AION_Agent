"""Verifica della firma ``X-Hub-Signature-256`` dei webhook Meta."""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

_PREFIX = "sha256="


def compute_signature(raw_body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256)
    return _PREFIX + digest.hexdigest()


def verify_signature(
    raw_body: bytes, header: Optional[str], app_secret: Optional[str]
) -> bool:
    """HMAC-SHA256 del body grezzo con l'app secret, confronto a tempo costante."""
    if not header or not app_secret:
        return False
    header = header.strip()
    if not header.lower().startswith(_PREFIX):
        return False
    expected = compute_signature(raw_body, app_secret)
    return hmac.compare_digest(expected, _PREFIX + header[len(_PREFIX) :].lower())
