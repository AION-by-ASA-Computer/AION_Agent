"""Accesso delegato a un progetto SQL QueryMemory, per una sola conversazione.

Caso d'uso: un assistente Telegram *condiviso* in un gruppo risponde a chiunque
lo interroghi usando il progetto del bot con i permessi del suo **creatore**
(che ne è responsabile, come di chi è nel gruppo). Il turno resta di chi scrive
(conversazione, memoria personale); solo i controlli d'accesso al progetto usano
l'utente delegato.

La delega vale per la coppia (conversazione, progetto) ed è attiva solo durante
il turno: il canale la concede con :func:`delegated` attorno a ``run_stream``.
Senza deleghe ogni funzione restituisce l'utente originale: il comportamento di
AION non cambia.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator, Optional, Tuple

# session_id -> (progetto in minuscolo, utente delegato)
_GRANTS: Dict[str, Tuple[str, str]] = {}


def _norm(project_slug: Optional[str]) -> str:
    return (project_slug or "").strip().lower()


def grant(session_id: str, project_slug: str, delegate_user_id: str) -> None:
    _GRANTS[session_id] = (_norm(project_slug), delegate_user_id)


def revoke(session_id: str) -> None:
    _GRANTS.pop(session_id, None)


def project_user(
    session_id: Optional[str], user_id: str, project_slug: Optional[str]
) -> str:
    """Utente con cui verificare l'accesso al progetto in questa conversazione."""
    if not session_id:
        return user_id
    hit = _GRANTS.get(session_id)
    if hit is not None and hit[0] == _norm(project_slug):
        return hit[1]
    return user_id


@contextmanager
def delegated(
    session_id: str, project_slug: Optional[str], delegate_user_id: Optional[str]
) -> Iterator[None]:
    """Delega attiva per la durata del blocco (nessuna se manca progetto o utente)."""
    if not _norm(project_slug) or not delegate_user_id:
        yield
        return
    grant(session_id, project_slug, delegate_user_id)
    try:
        yield
    finally:
        revoke(session_id)
