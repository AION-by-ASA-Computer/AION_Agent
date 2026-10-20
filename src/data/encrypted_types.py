"""Tipi colonna cifrati a riposo.

``EncryptedOAuthConfigJSON`` cifra il ``client_secret`` dentro il JSON di
``mcp_server_configs.oauth_config`` con ``AION_CREDENTIAL_ENCRYPTION_KEY``
(AES-GCM, vedi :mod:`src.runtime.credential_store`). I chiamanti continuano a
leggere e scrivere JSON con ``client_secret`` in chiaro: la cifratura avviene
solo al confine col DB.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger("aion.data.encrypted_types")

_PLAIN_KEY = "client_secret"
_ENC_KEY = "client_secret_encrypted"


def _parse_dict(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return cfg if isinstance(cfg, dict) else None


def encrypt_oauth_config_json(raw: Optional[str]) -> Optional[str]:
    """``client_secret`` in chiaro → ``client_secret_encrypted``. Idempotente."""
    cfg = _parse_dict(raw)
    if cfg is None or _PLAIN_KEY not in cfg:
        return raw
    from src.runtime.credential_store import encrypt_value

    secret = str(cfg.pop(_PLAIN_KEY) or "").strip()
    if secret:
        cfg[_ENC_KEY] = encrypt_value(secret)
    else:
        cfg.pop(_ENC_KEY, None)
    return json.dumps(cfg)


def decrypt_oauth_config_json(raw: Optional[str]) -> Optional[str]:
    """``client_secret_encrypted`` → ``client_secret``; il chiaro legacy passa invariato.

    Se il segreto non è decifrabile (chiave cambiata) il config viene restituito
    senza ``client_secret``: la riga resta leggibile e il flusso OAuth segnala
    il client come non configurato.
    """
    cfg = _parse_dict(raw)
    if cfg is None or _ENC_KEY not in cfg:
        return raw
    from src.runtime.credential_store import CredentialDecryptionError, decrypt_value

    encrypted = cfg.pop(_ENC_KEY)
    if encrypted and not cfg.get(_PLAIN_KEY):
        try:
            cfg[_PLAIN_KEY] = decrypt_value(str(encrypted))
        except CredentialDecryptionError as exc:
            logger.error("client_secret OAuth MCP non decifrabile: %s", exc)
    return json.dumps(cfg)


class EncryptedOAuthConfigJSON(TypeDecorator):
    """Colonna TEXT con JSON oauth_config; ``client_secret`` cifrato a riposo."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        return encrypt_oauth_config_json(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        return decrypt_oauth_config_json(value)
