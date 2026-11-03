"""Settings del canale Telegram, lette da ``.env`` con prefisso ``AION_TELEGRAM_``.

Modulo volutamente privo di import di aiogram: con il flag spento AION non
deve caricare nulla del canale.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AION_TELEGRAM_",
        env_file=".env",
        extra="ignore",
    )

    enabled: bool = False
    # Token del bot manager (@BotFather). SecretStr: mai in repr/log.
    manager_token: Optional[SecretStr] = None
    # Proxy HTTP(S)/SOCKS verso api.telegram.org (es. proxy aziendale).
    proxy_url: Optional[str] = None
    # Long polling: secondi di attesa lato Telegram per ogni getUpdates.
    polling_timeout: int = 50
    # Allo shutdown: attesa massima degli handler in corso prima di confermare l'offset.
    shutdown_grace_sec: float = 10.0
    # Validità dei link di collegamento generati da Impostazioni → Telegram.
    pairing_code_ttl_min: int = 15
    # Chat sul bot manager. Di default no: il manager gestisce account e assistenti,
    # si chatta con gli assistenti personali. 1 = emergenza (es. managed bot non disponibili).
    manager_chat: bool = False
    # Profilo proposto per primo nei nuovi assistenti (e della chat sul manager, se attiva).
    default_profile: str = "generic_assistant"
    # Turni dell'agente in parallelo per tutti gli utenti Telegram (gli altri attendono in coda).
    max_concurrent_jobs: int = 1
    # Aggiornamento della risposta in streaming su Telegram (limite ~1 msg/s per chat).
    stream_edit_interval_ms: int = 1000
    # Durata massima di un turno dell'agente avviato da Telegram.
    turn_timeout_sec: int = 900
    # Mostra i tool chiamati dall'agente (in streaming e in fondo alla risposta).
    show_tools: bool = True
    # Risposte nel formato rich di Telegram (tabelle vere, sezioni richiudibili);
    # se il bot non lo supporta si torna da soli all'HTML.
    rich_messages: bool = True
    # Ragionamento del modello in una sezione richiudibile (solo formato rich).
    show_reasoning: bool = True
    # Bot personali (/newbot) per utente AION, esclusi quelli eliminati.
    max_bots_per_user: int = 3
    # Bot personali in ascolto (long polling) contemporaneamente: rete di sicurezza.
    max_running_bots: int = 200
    # Controllo periodico degli assistenti (nome/username, ripresa dagli errori,
    # bot cancellati da @BotFather). 0 = disattivato.
    reconcile_interval_min: int = 30
    # Policy del canale: slug separati da virgola non usabili da Telegram
    # (non compaiono in /newbot, /mybots, /profile, /project e vengono rifiutati).
    blocked_profiles: str = ""
    blocked_projects: str = ""

    @staticmethod
    def _slugs(raw: str) -> frozenset:
        return frozenset(x.strip().lower() for x in (raw or "").split(",") if x.strip())

    @property
    def blocked_profile_set(self) -> frozenset:
        return self._slugs(self.blocked_profiles)

    @property
    def blocked_project_set(self) -> frozenset:
        return self._slugs(self.blocked_projects)

    @field_validator("manager_token", "proxy_url", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def manager_token_value(self) -> Optional[str]:
        if self.manager_token is None:
            return None
        return self.manager_token.get_secret_value().strip() or None


@lru_cache
def get_telegram_settings() -> TelegramSettings:
    return TelegramSettings()
