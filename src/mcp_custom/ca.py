"""Company certificate authority for custom MCP jails.

Internal applications (CRM, ERP, Plane, database gateways) are often served over
HTTPS with certificates signed by a company CA that the jail image does not know:
without it every connection fails with a certificate error. The admin uploads the
company CA from admin-ui (Settings -> Network, stored by ``src/security/company_ca.py``)
or, on the server, points ``AION_SANDBOX_CA_BUNDLE`` to a PEM file (this wins);
this module writes ``mcp_servers/custom/.ca/ca-bundle.pem``
= public roots (certifi) + company CA, and the jails mount it read-only at
``/etc/aion/ca-bundle.pem`` with the usual variables pointing to it.

The public roots are kept on purpose: a bundle with the company CA alone would
break every HTTPS call to the internet. Used by ``runtime`` (server processes)
and ``verify`` (dependency build: private package indexes; probe).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

from .paths import custom_root

logger = logging.getLogger("aion.mcp_custom.ca")

# Where the bundle is mounted inside the jails.
CA_IN_CONTAINER = "/etc/aion/ca-bundle.pem"

# Variables read by the common TLS stacks: Python ssl/httpx (SSL_CERT_FILE),
# requests, curl, pip, Node (extra CAs, additive).
_CA_ENV_KEYS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "PIP_CERT",
    "NODE_EXTRA_CA_CERTS",
)

# (source path, mtime, size) of the last bundle written, to skip rewriting it at
# every server start.
_last: Dict[str, Tuple[str, float, int]] = {}


def jail_ca_bundle() -> Optional[Path]:
    """Path of the combined bundle under ``mcp_servers/custom/.ca``, or None.

    None when no company CA is configured (or it is unreadable, logged): jails
    then trust the public roots of their image only, and a bundle left by a CA
    removed from the panel is deleted.
    """
    from ..security.company_ca import active_ca_source

    src = active_ca_source()
    target = custom_root() / ".ca" / "ca-bundle.pem"
    if src is None:
        if target.exists():
            target.unlink(missing_ok=True)
        _last.pop("bundle", None)
        return None
    source = str(src)
    try:
        stat = src.stat()
    except OSError:
        logger.warning("company CA %s not readable: not added to jails", source)
        return None
    key = (source, stat.st_mtime, stat.st_size)
    if _last.get("bundle") == key and target.is_file():
        return target

    company = src.read_text(encoding="utf-8", errors="replace")
    if "BEGIN CERTIFICATE" not in company:
        logger.warning("company CA %s holds no PEM certificate: ignored", source)
        return None
    import certifi

    public = Path(certifi.where()).read_text(encoding="utf-8")
    combined = (
        public.rstrip()
        + "\n\n# --- Company CA (AION Settings -> Network) ---\n"
        + company.strip()
        + "\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if (
        not target.is_file()
        or target.read_text(encoding="utf-8", errors="replace") != combined
    ):
        tmp = target.with_suffix(".tmp")
        tmp.write_text(combined, encoding="utf-8")
        os.chmod(tmp, 0o644)  # read by the unprivileged jail user
        tmp.replace(target)
    _last["bundle"] = key
    return target


def ca_env(bundle_path: str) -> Dict[str, str]:
    """Variables that make Python, pip, curl and Node trust ``bundle_path``."""
    return {k: bundle_path for k in _CA_ENV_KEYS}
