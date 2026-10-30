"""Firma ``X-Hub-Signature-256`` dei webhook Meta."""

from src.channels.whatsapp.signature import compute_signature, verify_signature

RAW = b'{"object":"whatsapp_business_account"}'
SECRET = "app-secret"


def test_valid_signature():
    assert verify_signature(RAW, compute_signature(RAW, SECRET), SECRET)


def test_uppercase_hex_accepted():
    sig = compute_signature(RAW, SECRET)
    assert verify_signature(RAW, "sha256=" + sig[7:].upper(), SECRET)


def test_tampered_body_rejected():
    sig = compute_signature(RAW, SECRET)
    assert not verify_signature(RAW + b" ", sig, SECRET)


def test_wrong_secret_rejected():
    assert not verify_signature(RAW, compute_signature(RAW, "other"), SECRET)


def test_missing_or_malformed_header_rejected():
    assert not verify_signature(RAW, None, SECRET)
    assert not verify_signature(RAW, "", SECRET)
    assert not verify_signature(RAW, compute_signature(RAW, SECRET)[7:], SECRET)
    assert not verify_signature(RAW, "sha1=abc", SECRET)


def test_missing_secret_rejected():
    assert not verify_signature(RAW, compute_signature(RAW, SECRET), None)
