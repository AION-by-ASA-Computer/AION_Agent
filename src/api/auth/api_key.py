from __future__ import annotations

import json
import os
import secrets
import string
from dataclasses import dataclass
from typing import Any, List, Optional

import bcrypt

from src.security.api_key_parse import parse_api_key

__all__ = [
    "generate_api_key_pair",
    "hash_secret",
    "hash_api_key",
    "verify_api_key",
    "parse_api_key",
]


def generate_api_key_pair() -> tuple[str, str, str]:
    """Return (full_key, prefix8, secret32)."""
    alphabet = string.ascii_lowercase + string.digits
    prefix = "".join(secrets.choice(alphabet) for _ in range(8))
    secret = "".join(secrets.choice(alphabet) for _ in range(32))
    full_key = f"aion_{prefix}_{secret}"
    return full_key, prefix, secret


def hash_secret(secret: str) -> str:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt()).decode()


def hash_api_key(key: str) -> str:
    """Hash the full API key or just the secret part."""
    return hash_secret(key)


def verify_api_key(secret: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(secret.encode(), hashed.encode())
    except Exception:
        return False
