"""Credential form fields that depend on admin configuration, not on the catalog.

The catalog and the registry env are static, but some connectors need a
variable number of credentials.  ``smb_files`` is the first: every file
server belongs to a *credential set* (servers in the same AD domain share one
Windows account), and each set other than ``DEFAULT`` needs its own
``SMB_USERNAME__<SET>`` / ``SMB_PASSWORD__<SET>`` pair.  Those values reach the
MCP process through the ``${AION_USER_SMB_FILES__*}`` wildcard placeholder
(see ``credential_store.resolve_user_credential_string``).

Used by the integrations API:

* ``integration_row_to_public_dict`` -> :func:`apply_dynamic_credential_fields`
  adds the per-set fields to the "My integrations" form;
* ``credential_key_is_write_only`` -> :func:`dynamic_key_is_write_only` so the
  extra passwords are never readable back, like ``SMB_PASSWORD``;
* ``POST /v1/integrations/credentials`` -> :func:`credential_key_allowed`, so
  the wildcard JSON cannot be stuffed with arbitrary keys.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger("aion.runtime.dynamic_credential_fields")

_SMB_SLUG = "smb_files"
# DEFAULT pair, or a pair of a named set (same format the admin API enforces).
_SMB_KEY_RE = re.compile(r"^SMB_(USERNAME|PASSWORD)(?:__([A-Z0-9]{1,24}))?$")


def _norm_slug(server_slug: str) -> str:
    """``smb-files`` and ``smb_files`` name the same connector."""
    return (server_slug or "").strip().lower().replace("-", "_")


def credential_key_allowed(server_slug: str, key: str) -> bool:
    """Whether a user may save ``key`` for this connector.

    Only connectors with dynamic fields are restricted; for ``smb_files`` the
    allowed keys are the DEFAULT pair and ``SMB_(USERNAME|PASSWORD)__<SET>``.
    ``__DEFAULT`` is rejected: that set lives in the plain keys.
    """
    if _norm_slug(server_slug) != _SMB_SLUG:
        return True
    m = _SMB_KEY_RE.match((key or "").strip())
    return bool(m) and m.group(2) != "DEFAULT"


def dynamic_key_is_write_only(server_slug: str, key: str) -> bool:
    """True for every SMB password key, whatever its set (no DB lookup needed)."""
    if _norm_slug(server_slug) != _SMB_SLUG:
        return False
    m = _SMB_KEY_RE.match((key or "").strip())
    return bool(m) and m.group(1) == "PASSWORD"


async def apply_dynamic_credential_fields(
    schema: List[Dict[str, Any]], server_slug: str, tenant_id: str
) -> List[Dict[str, Any]]:
    """Return ``schema`` completed with the admin-dependent fields.

    Never raises: on any error the static schema is returned unchanged (the
    form must still render).  Does not mutate the input list.
    """
    if _norm_slug(server_slug) != _SMB_SLUG:
        return schema
    try:
        return await _smb_fields(schema, tenant_id)
    except Exception:
        logger.warning("SMB dynamic credential fields unavailable", exc_info=True)
        return schema


async def _smb_fields(
    schema: List[Dict[str, Any]], tenant_id: str
) -> List[Dict[str, Any]]:
    """Name the servers of each credential set and add the extra-set pairs.

    Extra sets are optional (``required: false``): with NTFS-only visibility a
    user may have an account in one domain only, so ``is_configured`` stays
    driven by the DEFAULT pair.
    """
    from src.tools.smb_files.credentials import credential_keys
    from src.tools.smb_files.settings_store import (
        DEFAULT_CREDENTIAL_SET,
        get_smb_config,
    )

    cfg = await get_smb_config(tenant_id)
    if cfg is None:
        return schema
    sets = cfg.credential_sets()
    out = [dict(f) for f in schema]

    # DEFAULT keeps the catalog labels; only say which servers it unlocks.
    default_aliases = sets.get(DEFAULT_CREDENTIAL_SET)
    if default_aliases:
        for field in out:
            if field.get("key") in credential_keys(DEFAULT_CREDENTIAL_SET):
                field["description"] = "Server: " + ", ".join(default_aliases)

    present = {str(f.get("key")) for f in out if f.get("key")}
    for cred_set, aliases in sorted(sets.items()):
        if cred_set == DEFAULT_CREDENTIAL_SET:
            continue
        user_key, pass_key = credential_keys(cred_set)
        servers = "Server: " + ", ".join(aliases)
        # "basic" keeps them next to the DEFAULT pair instead of under "Advanced".
        if user_key not in present:
            out.append(
                {
                    "key": user_key,
                    "label": f"Utente Windows ({cred_set})",
                    "type": "text",
                    "required": False,
                    "category": "basic",
                    "description": servers,
                }
            )
        if pass_key not in present:
            out.append(
                {
                    "key": pass_key,
                    "label": f"Password Windows ({cred_set})",
                    "type": "password",
                    "write_only": True,
                    "required": False,
                    "category": "basic",
                    "description": servers,
                }
            )
    return out
