"""Company CA uploaded from admin-ui Settings -> Network (src/security/company_ca.py, /admin/network).

Covers validation (PEM, DER, garbage, empty), storage in the data volume, the
precedence of AION_SANDBOX_CA_BUNDLE, the combined jail bundle and the endpoints
(immediate application to running custom servers, audit, read-only under env).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import src.aion_env  # noqa: F401
from src.security import company_ca


def _make_cert(*, ca: bool = True, expired: bool = False, cn: str = "Azienda Root CA"):
    """Self-signed certificate for the tests (PEM bytes, DER bytes)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    start, end = (
        (now - timedelta(days=30), now - timedelta(days=1))
        if expired
        else (now - timedelta(days=1), now + timedelta(days=365))
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM), cert.public_bytes(
        serialization.Encoding.DER
    )


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """CA store and jail bundle in a temp folder; no env override."""
    monkeypatch.setattr(company_ca, "store_dir", lambda: tmp_path / "network")
    monkeypatch.delenv("AION_SANDBOX_CA_BUNDLE", raising=False)
    from src.mcp_custom import ca

    monkeypatch.setattr(ca, "custom_root", lambda: tmp_path / "custom")
    ca._last.clear()
    return tmp_path


def test_pem_upload_is_stored_and_described():
    """A PEM CA is stored in the data volume and described (subject, expiry, CA flag)."""
    pem, _ = _make_cert()
    out = company_ca.save_uploaded_ca(pem, filename="azienda.pem", actor="admin")
    assert out["source"] == "upload" and out["filename"] == "azienda.pem"
    assert out["certificates"][0]["subject"] == "CN=Azienda Root CA"
    assert out["certificates"][0]["is_ca"] is True and out["warnings"] == []
    assert company_ca.active_ca_source() == company_ca.stored_ca_path()


def test_der_upload_is_normalised_to_pem():
    """A DER certificate (.cer/.der from Windows) is accepted and stored as PEM."""
    _, der = _make_cert()
    company_ca.save_uploaded_ca(der, filename="azienda.cer", actor="admin")
    assert (
        company_ca.stored_ca_path()
        .read_text(encoding="ascii")
        .startswith("-----BEGIN CERTIFICATE-----")
    )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"hello",
        b"-----BEGIN CERTIFICATE-----\nbroken\n-----END CERTIFICATE-----\n",
    ],
)
def test_invalid_files_are_rejected(data: bytes):
    """Empty, random or broken files are rejected with a message and nothing is stored."""
    with pytest.raises(company_ca.CompanyCAError):
        company_ca.save_uploaded_ca(data, filename="x.pem", actor="admin")
    assert company_ca.active_ca_source() is None


def test_expired_or_leaf_certificates_are_accepted_with_warnings():
    """Expired or non-CA certificates are stored but flagged to the admin."""
    pem, _ = _make_cert(ca=False, expired=True, cn="crm.azienda.local")
    out = company_ca.save_uploaded_ca(pem, filename="crm.pem", actor="admin")
    assert any("expired" in w for w in out["warnings"]) and any(
        "not a CA" in w for w in out["warnings"]
    )


def test_env_override_wins_over_upload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """AION_SANDBOX_CA_BUNDLE set on the server wins over the uploaded file."""
    pem, _ = _make_cert()
    company_ca.save_uploaded_ca(pem, filename="a.pem", actor="admin")
    env_file = tmp_path / "env-ca.pem"
    env_file.write_bytes(pem)
    monkeypatch.setenv("AION_SANDBOX_CA_BUNDLE", str(env_file))
    assert company_ca.active_ca_source() == env_file
    assert company_ca.describe_active()["source"] == "env"


def test_uploaded_ca_reaches_the_jail_bundle_and_removal_cleans_it():
    """Upload -> combined bundle with the company CA; removal -> bundle deleted."""
    from src.mcp_custom.ca import jail_ca_bundle

    pem, _ = _make_cert()
    company_ca.save_uploaded_ca(pem, filename="a.pem", actor="admin")
    bundle = jail_ca_bundle()
    assert bundle is not None and pem.decode().strip() in bundle.read_text(
        encoding="utf-8"
    )
    assert company_ca.remove_uploaded_ca() is True
    assert jail_ca_bundle() is None and not bundle.exists()


def test_endpoint_upload_applies_immediately_and_audits(
    monkeypatch: pytest.MonkeyPatch,
):
    """PUT /admin/network/ca restarts running custom servers and writes the audit row."""
    from src.api import admin_network

    apply = AsyncMock(return_value=2)
    audit = AsyncMock()
    monkeypatch.setattr(admin_network, "_apply_to_running_servers", apply)
    monkeypatch.setattr(admin_network, "_audit", audit)
    monkeypatch.setattr(
        admin_network, "_network_summary", lambda: {"default_level": "lan"}
    )
    pem, _ = _make_cert()

    class _Upload:
        filename = "azienda.pem"

        async def read(self, _n):
            return pem

    auth = type("A", (), {"identifier": "admin", "user_row_id": None})()
    out = asyncio.run(admin_network.put_company_ca(file=_Upload(), auth=auth))
    assert out["servers_restarted"] == 2 and out["source"] == "upload"
    assert audit.await_args.args[1] == "network.company_ca.upload"


def test_endpoint_refuses_changes_when_env_manages_the_ca(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """With AION_SANDBOX_CA_BUNDLE set the panel is read-only (409)."""
    from fastapi import HTTPException

    from src.api import admin_network

    monkeypatch.setenv("AION_SANDBOX_CA_BUNDLE", str(tmp_path / "x.pem"))
    auth = type("A", (), {"identifier": "admin", "user_row_id": None})()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_network.delete_company_ca(auth=auth))
    assert exc.value.status_code == 409
