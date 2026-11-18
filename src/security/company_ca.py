"""Company certificate authority uploaded from admin-ui (Settings -> Network).

Internal applications (CRM, ERP, Plane, database gateways) often use HTTPS
certificates signed by a company CA. The admin uploads that CA once from the
admin panel; it is validated, normalised to PEM and stored in the AION data volume
(``<data>/network/company-ca.pem`` + ``company-ca.json`` metadata), so it survives
upgrades and container recreation and needs no ``.env`` edit nor restart.

Precedence: ``AION_SANDBOX_CA_BUNDLE`` (set by whoever runs the server) wins over
the upload and makes the panel read-only.

Used by ``src/api/admin_network.py`` (upload/remove/describe) and by
``src/mcp_custom/ca.py`` (combined bundle mounted in the jails).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_CA_BYTES = 1024 * 1024
MAX_CERTIFICATES = 50


class CompanyCAError(ValueError):
    """The uploaded file is not a usable certificate (message shown in admin-ui)."""


def store_dir() -> Path:
    from ..session_workspace import data_root

    return data_root() / "network"


def stored_ca_path() -> Path:
    return store_dir() / "company-ca.pem"


def _meta_path() -> Path:
    return store_dir() / "company-ca.json"


def env_override() -> str:
    """``AION_SANDBOX_CA_BUNDLE`` when set: it wins over the uploaded file."""
    return (os.environ.get("AION_SANDBOX_CA_BUNDLE") or "").strip()


def active_ca_source() -> Optional[Path]:
    """File AION must trust: the env override, else the uploaded CA, else None."""
    override = env_override()
    if override:
        return Path(override)
    path = stored_ca_path()
    return path if path.is_file() else None


@dataclass
class _Parsed:
    pem: str
    certificates: List[Dict[str, Any]]
    warnings: List[str]


def _describe(cert) -> Dict[str, Any]:
    """Human-readable summary of one certificate for the admin panel."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    try:
        is_ca = bool(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
    except x509.ExtensionNotFound:
        is_ca = False
    not_after = cert.not_valid_after_utc
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": not_after.isoformat(),
        "expired": not_after < datetime.now(timezone.utc),
        "is_ca": is_ca,
        "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(":").upper(),
    }


def parse_certificates(data: bytes) -> _Parsed:
    """Validate PEM (one or more certificates) or DER (one certificate).

    Raises ``CompanyCAError`` when nothing usable is found. Expired or non-CA
    certificates are accepted with a warning: a self-signed server certificate can
    legitimately be trusted directly.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    if not data:
        raise CompanyCAError("the file is empty")
    if len(data) > MAX_CA_BYTES:
        raise CompanyCAError("the file is too large (maximum 1 MB)")
    try:
        if b"-----BEGIN CERTIFICATE-----" in data:
            certs = x509.load_pem_x509_certificates(data)
        else:
            certs = [x509.load_der_x509_certificate(data)]
    except ValueError as exc:
        raise CompanyCAError("the file is not a valid certificate (PEM .pem/.crt or DER .cer/.der expected)") from exc
    if len(certs) > MAX_CERTIFICATES:
        raise CompanyCAError(f"too many certificates in the file (maximum {MAX_CERTIFICATES})")

    described = [_describe(c) for c in certs]
    warnings: List[str] = []
    for d in described:
        if d["expired"]:
            warnings.append(f"expired certificate: {d['subject']}")
        if not d["is_ca"]:
            warnings.append(f"not a CA certificate (trusted as is): {d['subject']}")
    pem = "".join(c.public_bytes(Encoding.PEM).decode("ascii") for c in certs)
    return _Parsed(pem=pem, certificates=described, warnings=warnings)


def save_uploaded_ca(data: bytes, *, filename: str, actor: str) -> Dict[str, Any]:
    """Validate and store an uploaded CA; returns its description."""
    parsed = parse_certificates(data)
    folder = store_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = stored_ca_path().with_suffix(".tmp")
    tmp.write_text(parsed.pem, encoding="ascii")
    os.chmod(tmp, 0o644)
    tmp.replace(stored_ca_path())
    meta = {
        "filename": Path(filename or "company-ca.pem").name,
        "uploaded_by": actor,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(parsed.pem.encode("ascii")).hexdigest(),
    }
    _meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {**describe_active(), "warnings": parsed.warnings}


def remove_uploaded_ca() -> bool:
    """Delete the uploaded CA; returns True when there was one."""
    existed = stored_ca_path().is_file()
    stored_ca_path().unlink(missing_ok=True)
    _meta_path().unlink(missing_ok=True)
    return existed


def describe_active() -> Dict[str, Any]:
    """State shown in admin-ui: source, certificates, upload metadata."""
    override = env_override()
    if override:
        source, path, meta = "env", Path(override), {}
    elif stored_ca_path().is_file():
        source, path = "upload", stored_ca_path()
        try:
            meta = json.loads(_meta_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    else:
        return {"source": None, "certificates": [], "env_path": None}
    try:
        certificates = parse_certificates(path.read_bytes()).certificates
        error = None
    except (OSError, CompanyCAError) as exc:
        certificates, error = [], str(exc)
    return {
        "source": source,
        "env_path": override or None,
        "certificates": certificates,
        "error": error,
        **{k: meta.get(k) for k in ("filename", "uploaded_by", "uploaded_at")},
    }
