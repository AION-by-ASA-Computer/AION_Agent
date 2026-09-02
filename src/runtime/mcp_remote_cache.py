"""
Pre-seeding della cache token di mcp-remote per prevenire l'apertura del browser.

mcp-remote (NodeOAuthClientProvider) legge i token dalla sua cache PRIMA di ogni
request. Se trova un refresh_token valido in cache, usa la grant refresh_token
via HTTP silenzioso invece di aprire il browser.

Struttura cache mcp-remote:
  <HOME>/.mcp-auth/mcp-remote-<version>/<serverUrlHash>_tokens.json
  <HOME>/.mcp-auth/mcp-remote-<version>/<serverUrlHash>_client_info.json

dove:
  - HOME è isolato per utente da _apply_mcp_home_isolation:
      data/users/<uid>/mcp_home
  - serverUrlHash = md5(server_url) — stesso algoritmo del sorgente mcp-remote
  - version viene letta dal package.json di mcp-remote

Questo modulo viene chiamato da credential_store._persist_oauth_tokens ogni
volta che AION scrive/rinnova un token, in modo che la cache mcp-remote sia
sempre allineata con il DB.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("aion.mcp_remote_cache")

# Versione di mcp-remote installata (letta dal package.json)
_MCP_REMOTE_VERSION: Optional[str] = None


def _get_mcp_remote_version() -> str:
    """Legge la versione di mcp-remote dal package.json installato."""
    global _MCP_REMOTE_VERSION
    if _MCP_REMOTE_VERSION is not None:
        return _MCP_REMOTE_VERSION

    # Cerca il package.json di mcp-remote nella cartella node_modules
    candidates = [
        # pnpm monorepo (struttura .pnpm/<pkg>@<ver>/node_modules/<pkg>/)
        Path(__file__).parent.parent.parent
        / "node_modules"
        / ".pnpm"
        / f"mcp-remote@0.1.38"
        / "node_modules"
        / "mcp-remote"
        / "package.json",
        # npm/yarn flat
        Path(__file__).parent.parent.parent
        / "node_modules"
        / "mcp-remote"
        / "package.json",
    ]

    for pkg_path in candidates:
        if pkg_path.exists():
            try:
                data = json.loads(pkg_path.read_text())
                version = data.get("version", "0.1.38")
                _MCP_REMOTE_VERSION = version
                logger.debug("mcp-remote version: %s (from %s)", version, pkg_path)
                return version
            except Exception as exc:
                logger.debug("Failed to read mcp-remote package.json at %s: %s", pkg_path, exc)

    # Fallback alla versione nota
    _MCP_REMOTE_VERSION = "0.1.38"
    logger.debug("mcp-remote version fallback: %s", _MCP_REMOTE_VERSION)
    return _MCP_REMOTE_VERSION


def _compute_server_url_hash(server_url: str) -> str:
    """
    Calcola il serverUrlHash come fa mcp-remote:
      md5(serverUrl)   (quando non ci sono headers o authorizeResource extra)

    In mcp-remote (chunk-65X3S4HB.js):
      function getServerUrlHash(serverUrl, authorizeResource, headers) {
        const parts = [serverUrl];
        if (authorizeResource) parts.push(authorizeResource);
        if (headers && Object.keys(headers).length > 0) {
          const sortedKeys = Object.keys(headers).sort();
          parts.push(JSON.stringify(headers, sortedKeys));
        }
        return crypto.createHash('md5').update(parts.join('|')).digest('hex');
      }

    NOTA: l'hash cambia se mcp-remote viene avviato con --header o --authorize-resource.
    Per il caso khub con --header Authorization: Bearer <token>, le headers cambiano
    ad ogni token → hash diverso! Usiamo solo server_url come base (senza headers)
    perché mcp-remote calcola l'hash al momento del lancio con i valori reali.

    La soluzione corretta è passare l'URL canonico del server (senza variabili).
    """
    return hashlib.md5(server_url.encode("utf-8")).hexdigest()




def _mcp_remote_config_dir(user_mcp_home: Path) -> Path:
    """Restituisce la directory di configurazione di mcp-remote per l'utente."""
    version = _get_mcp_remote_version()
    return user_mcp_home / ".mcp-auth" / f"mcp-remote-{version}"


def _get_user_mcp_home(user_id: str) -> Optional[Path]:
    """
    Restituisce la directory HOME isolata per l'utente MCP.
    Dipende dalla configurazione AION_MCP_USER_HOME_ISOLATION.
    """
    if os.getenv("AION_MCP_USER_HOME_ISOLATION", "1").lower() not in ("1", "true", "yes"):
        # Isolation disabilitata: usa la home reale del sistema
        return Path(os.path.expanduser("~"))

    from ..data.engine import data_root
    from ..identity import sanitize_user_id

    safe_uid = sanitize_user_id(user_id)
    return data_root() / "users" / safe_uid / "mcp_home"


async def seed_mcp_remote_token_cache(
    user_id: str,
    server_slug: str,
    token_data: Dict[str, Any],
    oauth_cfg: Dict[str, Any],
    *,
    server_url: Optional[str] = None,
) -> bool:
    """
    Scrive tokens.json e client_info.json nella cache di mcp-remote per l'utente.

    Args:
        user_id: ID utente AION
        server_slug: slug del server MCP (es. "khub")
        token_data: risposta OAuth (access_token, refresh_token, expires_in, ...)
        oauth_cfg: configurazione OAuth del server (client_id, client_secret, ...)
        server_url: URL del server MCP remoto (se None, lo ricava dalla registry)

    Returns:
        True se il seeding è avvenuto, False in caso di errore.
    """
    try:
        # Recupera URL del server dalla registry se non fornito
        if not server_url:
            server_url = _get_server_url_from_registry(server_slug)
        if not server_url:
            logger.debug(
                "mcp-remote cache seed: URL non trovato per server=%s, skip",
                server_slug,
            )
            return False

        user_home = _get_user_mcp_home(user_id)
        if not user_home:
            logger.debug("mcp-remote cache seed: HOME non trovata per user=%s, skip", user_id)
            return False

        config_dir = _mcp_remote_config_dir(user_home)
        config_dir.mkdir(parents=True, exist_ok=True)

        url_hash = _compute_server_url_hash(server_url)

        access_token = str(token_data.get("access_token", ""))
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 300)
        scope = token_data.get("scope", "openid email profile")
        token_type = token_data.get("token_type", "Bearer")

        client_id = oauth_cfg.get("client_id", "")
        client_secret = oauth_cfg.get("client_secret")

        # tokens.json — formato OAuthTokensSchema di mcp-remote
        tokens_path = config_dir / f"{url_hash}_tokens.json"
        tokens_payload: Dict[str, Any] = {
            "access_token": access_token,
            "token_type": token_type,
            "expires_in": int(expires_in) if expires_in else 300,
            "scope": scope,
        }
        if refresh_token:
            tokens_payload["refresh_token"] = refresh_token

        tokens_path.write_text(
            json.dumps(tokens_payload, indent=2), encoding="utf-8"
        )
        tokens_path.chmod(0o600)

        # client_info.json — OAuthClientInformationFullSchema di mcp-remote
        if client_id:
            client_info: Dict[str, Any] = {
                "client_id": client_id,
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            }
            if client_secret:
                client_info["client_secret"] = client_secret
                client_info["client_secret_expires_at"] = 0

            client_info_path = config_dir / f"{url_hash}_client_info.json"
            client_info_path.write_text(
                json.dumps(client_info, indent=2), encoding="utf-8"
            )
            client_info_path.chmod(0o600)

        logger.debug(
            "mcp-remote cache seeded: user=%s server=%s hash=%s refresh=%s path=%s",
            user_id,
            server_slug,
            url_hash[:8],
            "yes" if refresh_token else "no",
            config_dir,
        )

        logger.info(
            "🔑 mcp-remote cache aggiornata: user=%s server=%s (browser auth disabilitato)",
            user_id,
            server_slug,
        )
        return True

    except Exception as exc:
        logger.warning(
            "mcp-remote cache seed fallito: user=%s server=%s reason=%s",
            user_id,
            server_slug,
            exc,
        )
        return False


def _get_server_url_from_registry(server_slug: str) -> Optional[str]:
    """
    Recupera l'URL remoto del server MCP dalla registry di AION.
    Cerca 'url' o 'remote_url' nella configurazione del server.
    """
    try:
        from ..mcp_manager import mcp_manager

        cfg = mcp_manager.get_server_config(server_slug) or {}
        return cfg.get("url") or cfg.get("remote_url") or None
    except Exception as exc:
        logger.debug("Impossibile leggere config per server=%s: %s", server_slug, exc)
        return None
