# src/api/version_check.py
"""
Endpoint GET /admin/version-check

Risponde con la versione corrente installata e l'ultima release disponibile
su GitHub, permettendo all'admin-ui di mostrare un banner non bloccante
quando è disponibile un aggiornamento.

Nessuna autenticazione GitHub richiesta: l'API pubblica consente 60 req/ora
per IP. La cache in-memory di 5 minuti garantisce al massimo ~12 chiamate/ora
indipendentemente dal numero di admin connessi.
"""
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("aion.api.version_check")

# Cache in-memory: evita rate-limit GitHub (60 req/ora anonime)
_CACHE_TTL_SEC = 300  # 5 minuti
_cache: dict = {}

router = APIRouter()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class VersionCheckResponse(BaseModel):
    current: str
    latest: str
    update_available: bool


# ---------------------------------------------------------------------------
# Helper: versione corrente
# ---------------------------------------------------------------------------


def _read_current_version() -> str:
    """Legge AION_VERSION da env (fonte primaria in deploy GHCR),
    con fallback a version.json nella root del repo."""
    v = os.environ.get("AION_VERSION", "").strip()
    if v and v != "latest":
        return v
    # Fallback: version.json (utile in sviluppo locale senza Docker)
    try:
        import json

        vfile = Path(__file__).resolve().parents[2] / "version.json"
        return json.loads(vfile.read_text(encoding="utf-8")).get("version", "unknown")
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Helper: ultima release GitHub
# ---------------------------------------------------------------------------


async def _fetch_latest_release() -> str:
    """Interroga l'API pubblica GitHub per l'ultima release pubblicata.

    Timeout breve (5s). In caso di errore (rete, rate-limit, ecc.)
    restituisce "unknown" senza propagare eccezioni — il banner semplicemente
    non viene mostrato.
    """
    url = "https://api.github.com/repos/AION-by-ASA-Computer/AION_Agent/releases/latest"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                headers={"Accept": "application/vnd.github+json"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            tag: str = resp.json().get("tag_name", "")
            # I tag sono nella forma "vX.Y.Z" — rimuoviamo il prefisso "v"
            return tag.lstrip("v") if tag else "unknown"
    except Exception as exc:  # network, timeout, rate-limit, JSON parse
        logger.debug("version_check: GitHub API error: %s", exc)
        return "unknown"


# ---------------------------------------------------------------------------
# Helper: confronto semver
# ---------------------------------------------------------------------------


def _parse_semver(v: str) -> tuple[int, int, int]:
    """Parsa 'X.Y.Z' in (X, Y, Z). Ritorna (0, 0, 0) per stringhe non valide."""
    try:
        parts = v.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return (0, 0, 0)


def _semver_gt(a: str, b: str) -> bool:
    """Ritorna True se la versione 'a' è strettamente maggiore di 'b'."""
    if a == "unknown" or b == "unknown":
        return False
    return _parse_semver(a) > _parse_semver(b)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/version-check",
    response_model=VersionCheckResponse,
    summary="Controlla se è disponibile una nuova versione di AION",
    description=(
        "Restituisce la versione corrente installata e l'ultima release "
        "disponibile su GitHub. La risposta è cachata per 5 minuti per "
        "evitare di consumare il rate-limit dell'API GitHub pubblica."
    ),
)
async def version_check() -> VersionCheckResponse:
    now = time.monotonic()
    if "data" in _cache and now - _cache.get("ts", 0) < _CACHE_TTL_SEC:
        return _cache["data"]

    current = _read_current_version()
    latest = await _fetch_latest_release()

    result = VersionCheckResponse(
        current=current,
        latest=latest,
        update_available=_semver_gt(latest, current),
    )

    _cache["data"] = result
    _cache["ts"] = now

    logger.debug(
        "version_check: current=%s latest=%s update_available=%s",
        current,
        latest,
        result.update_available,
    )

    return result
