"""Identita' effettiva del chiamante e ownership di conversazioni/sessioni.

Regola unica per tutti gli endpoint user-facing: nessuno (admin inclusi) puo'
leggere o scrivere conversazioni, sessioni o file di un altro utente.

Identita' effettiva (``effective_user_id``):

- ``chat_token`` (password auth attiva): l'utente del token firmato. Header e
  body ``user_id`` vengono ignorati.
- ``internal`` (BFF server-to-server con ``X-AION-Chat-Ui-Secret``): unico
  caso con auth attiva in cui ``X-AION-User-Id`` e' attendibile.
- ``anonymous`` (password auth disattivata, modalita' aperta): header/body,
  fallback ``default``. Non c'e' autenticazione da far valere.
- ``api_key``: la chiave e' il proprio principal (``apikey_<id>``); non puo'
  impersonare utenti via header/body.

Ownership (``assert_conversation_access``): la riga ``conversations`` e' la
fonte di verita'. Per sessioni senza riga (es. upload prima del primo
messaggio) vale il marker ``.aion_owner`` nella root della sessione. In
qualunque caso di mismatch si risponde 404 per non rivelare l'esistenza della
risorsa.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, Header, HTTPException

from src.api.auth_login import ChatAuthIdentity, require_chat_auth
from src.chat_auth import password_auth_enabled
from src.identity import sanitize_user_id

logger = logging.getLogger("aion.api.ownership")

_OWNER_MARKER = ".aion_owner"
API_KEY_PRINCIPAL_PREFIX = "apikey_"


def api_key_principal(api_key_id: Optional[str]) -> str:
    return sanitize_user_id(f"{API_KEY_PRINCIPAL_PREFIX}{api_key_id or 'unknown'}")


def header_identity_trusted(auth: ChatAuthIdentity) -> bool:
    """True se ``X-AION-User-Id`` / body ``user_id`` possono definire l'utente."""
    return auth.via in ("anonymous", "internal")


def effective_user_id(
    auth: ChatAuthIdentity,
    *,
    header_user_id: Optional[str] = None,
    body_user_id: Optional[str] = None,
) -> str:
    if auth.via == "chat_token":
        return sanitize_user_id(auth.identifier or auth.user_row_id)
    if header_identity_trusted(auth):
        return sanitize_user_id(body_user_id or header_user_id)
    if auth.via == "api_key":
        return api_key_principal(auth.identifier)
    # Vie non previste (es. orch_secret): mai fidarsi dell'header.
    return sanitize_user_id(auth.identifier or auth.user_row_id)


async def chat_user_id(
    auth: ChatAuthIdentity = Depends(require_chat_auth),
    x_aion_user_id: Optional[str] = Header(None, alias="X-AION-User-Id"),
) -> str:
    """Dependency: utente effettivo per gli endpoint chat user-facing."""
    return effective_user_id(auth, header_user_id=x_aion_user_id)


def _tenant() -> str:
    return (os.getenv("AION_DEFAULT_TENANT_ID") or "default").strip() or "default"


def _unified_db_enabled() -> bool:
    return os.getenv("AION_UNIFIED_DB", "1").lower() in ("1", "true", "yes")


async def conversation_owner(conversation_id: str) -> Optional[tuple[str, str]]:
    """``(tenant_id, user_id)`` della conversazione, ``None`` se non esiste."""
    if not _unified_db_enabled():
        return None
    from src.data.engine import get_async_session_maker
    from src.data.models import Conversation

    async with get_async_session_maker()() as session:
        row = await session.get(Conversation, conversation_id)
    if row is None:
        return None
    return (row.tenant_id or "", row.user_id or "")


def _marker_path(session_id: str) -> Optional[str]:
    try:
        from src.session_workspace import session_fs

        return session_fs(session_id, _OWNER_MARKER)
    except ValueError:
        return None


def read_session_owner_marker(session_id: str) -> Optional[str]:
    path = _marker_path(session_id)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def claim_session_owner_marker(session_id: str, user_id: str) -> None:
    """Registra l'owner di una sessione che non ha ancora una riga DB."""
    path = _marker_path(session_id)
    if not path or os.path.exists(path):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(user_id)
    except FileExistsError:
        return
    except OSError as exc:
        logger.warning("owner marker write failed session=%s: %s", session_id[:8], exc)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Conversation not found")


async def assert_conversation_access(
    conversation_id: str,
    user_id: str,
    *,
    allow_missing: bool = False,
    claim_if_missing: bool = False,
) -> bool:
    """Verifica che ``user_id`` possa accedere a ``conversation_id``.

    Ritorna ``True`` se la conversazione esiste nel DB (ed e' dell'utente),
    ``False`` se non esiste ma l'accesso e' consentito. Solleva 404 altrimenti.

    - ``allow_missing``: consenti l'accesso se non c'e' riga DB e nessun marker
      di un altro utente (usato per scritture che creano la sessione).
    - ``claim_if_missing``: in quel caso scrive il marker ``.aion_owner``.

    Senza riga DB l'accesso in lettura e' consentito solo se il marker indica
    lo stesso utente; in modalita' aperta (auth disattivata) le sessioni
    legacy senza riga ne' marker restano leggibili.
    """
    uid = sanitize_user_id(user_id)
    owner = await conversation_owner(conversation_id)
    marker = read_session_owner_marker(conversation_id)
    if owner is not None:
        tenant_id, owner_uid = owner
        if tenant_id != _tenant() or sanitize_user_id(owner_uid) != uid:
            raise _not_found()
        # Riga e marker discordi (file caricati da A, riga creata da B): la
        # sessione e' contesa e non viene servita a nessuno.
        if marker is not None and sanitize_user_id(marker) != uid:
            raise _not_found()
        return True
    if marker is not None:
        if sanitize_user_id(marker) != uid:
            raise _not_found()
        return False
    if allow_missing:
        if claim_if_missing:
            claim_session_owner_marker(conversation_id, uid)
            # Due prime scritture concorrenti: vince chi crea il marker.
            claimed = read_session_owner_marker(conversation_id)
            if claimed is not None and sanitize_user_id(claimed) != uid:
                raise _not_found()
        return False
    if not password_auth_enabled():
        return False
    raise _not_found()


async def claim_conversation_for_write(conversation_id: str, user_id: str) -> bool:
    """Da chiamare prima di creare/aggiornare una riga ``conversations``.

    L'id della conversazione lo sceglie il client: senza questo controllo un
    utente potrebbe creare la riga su una sessione in cui un altro ha gia'
    caricato file (marker ``.aion_owner``) e appropriarsene. Rivendica la
    sessione se libera, 404 se appartiene ad altri.
    """
    return await assert_conversation_access(
        conversation_id, user_id, allow_missing=True, claim_if_missing=True
    )


def api_key_context_principal(ctx) -> str:
    """Principal di un ``AuthContext`` (router v1 con scope API key)."""
    if getattr(ctx, "user_id", None):
        return sanitize_user_id(ctx.user_id)
    return api_key_principal(getattr(ctx, "api_key_id", None))


def owned_by(row, tenant_id: str, user_id: str) -> bool:
    """True se la riga ``Conversation`` appartiene a ``(tenant_id, user_id)``."""
    return (
        row is not None
        and (row.tenant_id or "") == tenant_id
        and sanitize_user_id(row.user_id or "") == sanitize_user_id(user_id)
    )
