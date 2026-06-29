"""
khub_auth.py — Gestione token Keycloak per Knowledge Hub (KHUB_RAG).

Fornisce un singleton ``khub_token_manager`` che acquisisce e rinnova
automaticamente un token OAuth2 via grant ``client_credentials``
(Service Account). Nessun utente coinvolto.

Variabili d'ambiente richieste (in .env o shell):
    KHUB_ISSUER           — es. https://auth.example.com/realms/your-realm
    KHUB_CLIENT_ID     — client_id del Service Account AION
    KHUB_CLIENT_SECRET — client_secret del Service Account AION


Utilizzo:
    from src.khub_auth import khub_token_manager

    token = await khub_token_manager.get_token()
    # → str | None  (None se le env var non sono configurate)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger("aion.khub_auth")


class KhubTokenManager:
    """
    Gestisce il ciclo di vita del token Keycloak per KHUB_RAG.

    - Acquisisce il token al primo utilizzo (lazy).
    - Rinnova il token automaticamente 30 secondi prima della scadenza.
    - Thread-safe per contesti asyncio (usa ``asyncio.Lock``).
    - Se le variabili d'ambiente non sono configurate, restituisce ``None``
      e logga un warning, lasciando la connessione senza autenticazione
      (utile in ambienti di sviluppo locale senza Keycloak).
    """

    def __init__(self) -> None:
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        """Crea il Lock lazily per evitare problemi con l'event loop al modulo-import."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _token_url(self) -> Optional[str]:
        url = os.getenv("KHUB_ISSUER", "").rstrip("/")
        if not url:
            return None
        return f"{url}/protocol/openid-connect/token"

    async def get_token(self) -> Optional[str]:
        """
        Restituisce un token valido, rinnovandolo se necessario.

        Returns:
            str — access token Keycloak
            None — se le env var non sono configurate (dev mode)
        """
        async with self._get_lock():
            if self._access_token and time.time() < self._expires_at - 30:
                return self._access_token
            return await self._fetch_token()

    async def _fetch_token(self) -> Optional[str]:
        token_url = self._token_url()
        if not token_url:
            logger.warning(
                "KhubTokenManager: KHUB_ISSUER non configurati — "
                "la connessione al server MCP avverrà senza autenticazione."
            )
            return None

        client_id = os.getenv("KHUB_CLIENT_ID", "")
        client_secret = os.getenv("KHUB_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            logger.warning(
                "KhubTokenManager: KHUB_CLIENT_ID o KHUB_CLIENT_SECRET mancanti — "
                "la connessione al server MCP avverrà senza autenticazione."
            )
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                data = resp.json()

            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 300)
            self._expires_at = time.time() + expires_in
            logger.info(
                "KhubTokenManager: token acquisito con successo, scade in %ds.", expires_in
            )
            return self._access_token

        except httpx.HTTPStatusError as exc:
            logger.error(
                "KhubTokenManager: Keycloak ha rifiutato le credenziali (%d): %s",
                exc.response.status_code,
                exc.response.text,
            )
        except httpx.HTTPError as exc:
            logger.error(
                "KhubTokenManager: errore di rete durante l'acquisizione del token: %s", exc
            )
        except Exception as exc:
            logger.error("KhubTokenManager: errore imprevisto: %s", exc)

        # Reset in caso di errore — forza un nuovo tentativo alla prossima chiamata
        self._access_token = None
        self._expires_at = 0.0
        return None

    def invalidate(self) -> None:
        """Forza il rinnovo del token alla prossima chiamata a ``get_token()``."""
        self._access_token = None
        self._expires_at = 0.0


# Singleton condiviso da tutti i moduli che ne fanno uso
khub_token_manager = KhubTokenManager()
