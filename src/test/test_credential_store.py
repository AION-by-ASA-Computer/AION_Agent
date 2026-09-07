"""
Unit test per src/runtime/credential_store.py

Copre:
  1. Round-trip encrypt_value → decrypt_value
  2. Chiave sbagliata → CredentialDecryptionError (non UnicodeDecodeError)
  3. Blob legacy base64 (pre-AES-GCM) ancora decodificato
  4. Blob corrotto (non-base64) → CredentialDecryptionError
  5. Chiave mancante in produzione → CredentialDecryptionError
  6. Chiave mancante in dev → chiave di sviluppo di fallback (32 byte)
"""

from __future__ import annotations

import base64
import os

import pytest

from src.runtime.credential_store import (
    CredentialDecryptionError,
    _get_encryption_key,
    decrypt_value,
    encrypt_value,
)


# ---------------------------------------------------------------------------
# 1. Round-trip
# ---------------------------------------------------------------------------


def test_roundtrip(monkeypatch):
    """encrypt_value → decrypt_value restituisce il plaintext originale."""
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)

    plaintext = "sk-test-api-key-12345"
    assert decrypt_value(encrypt_value(plaintext)) == plaintext


def test_roundtrip_unicode(monkeypatch):
    """Funziona anche con caratteri non-ASCII nel plaintext."""
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)

    plaintext = "chiave-con-accenti-e-emoji"
    assert decrypt_value(encrypt_value(plaintext)) == plaintext


# ---------------------------------------------------------------------------
# 2. Chiave sbagliata
# ---------------------------------------------------------------------------


def test_wrong_key_raises_credential_decryption_error(monkeypatch):
    """
    Decifrare con una chiave diversa deve sollevare CredentialDecryptionError,
    NON UnicodeDecodeError (il bug originale segnalato in utf-8-error-plan.md).
    """
    key_a = os.urandom(32).hex()
    key_b = os.urandom(32).hex()

    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", key_a)
    monkeypatch.delenv("AION_ENV", raising=False)
    ciphertext = encrypt_value("secret-api-key")

    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", key_b)
    with pytest.raises(CredentialDecryptionError):
        decrypt_value(ciphertext)


def test_wrong_key_not_unicode_error(monkeypatch):
    """Verifica esplicitamente che l'eccezione NON sia UnicodeDecodeError."""
    key_a = os.urandom(32).hex()
    key_b = os.urandom(32).hex()

    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", key_a)
    monkeypatch.delenv("AION_ENV", raising=False)
    ciphertext = encrypt_value("another-secret")

    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", key_b)
    try:
        decrypt_value(ciphertext)
        pytest.fail("Doveva sollevare CredentialDecryptionError")
    except CredentialDecryptionError:
        pass  # Corretto
    except UnicodeDecodeError as exc:
        pytest.fail(
            f"UnicodeDecodeError sollevato invece di CredentialDecryptionError: {exc}"
        )


# ---------------------------------------------------------------------------
# 3. Blob legacy base64 (plaintext pre-AES-GCM)
# ---------------------------------------------------------------------------


def test_legacy_base64_blob_decoded(monkeypatch):
    """
    Un valore base64-encoded salvato in chiaro (formato pre-AES-GCM)
    viene ancora decodificato correttamente senza errori.
    """
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)

    legacy_plaintext = "old-plaintext-api-key"
    # Simuliamo un blob salvato prima dell'introduzione di AES-GCM:
    # solo base64 del testo in chiaro, senza nonce né tag.
    legacy_blob = base64.b64encode(legacy_plaintext.encode("utf-8")).decode("ascii")

    assert decrypt_value(legacy_blob) == legacy_plaintext


def test_legacy_blob_short_ascii(monkeypatch):
    """Blob corto (< 13 byte decodificati) viene trattato come legacy."""
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)

    short = base64.b64encode(b"abc").decode("ascii")  # 3 byte < 13
    assert decrypt_value(short) == "abc"


# ---------------------------------------------------------------------------
# 4. Blob corrotto
# ---------------------------------------------------------------------------


def test_corrupted_non_base64_raises(monkeypatch):
    """Input non-base64 solleva CredentialDecryptionError."""
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)

    with pytest.raises(CredentialDecryptionError):
        decrypt_value("not!valid!base64!!!")


def test_corrupted_truncated_ciphertext_raises(monkeypatch):
    """
    Un blob base64 valido ma con nonce/ciphertext troncato (dati corrotti)
    solleva CredentialDecryptionError.
    """
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(32).hex())
    monkeypatch.delenv("AION_ENV", raising=False)

    # 20 byte di dati casuali: abbastanza per passare il check len>12,
    # ma tag AES-GCM non corrispondente -> InvalidTag.
    garbage = base64.b64encode(os.urandom(20)).decode("ascii")
    with pytest.raises(CredentialDecryptionError):
        decrypt_value(garbage)


# ---------------------------------------------------------------------------
# 5. Chiave mancante in produzione
# ---------------------------------------------------------------------------


def test_missing_key_in_production_raises(monkeypatch):
    """
    Con AION_ENV=production e nessuna chiave impostata,
    _get_encryption_key() deve sollevare CredentialDecryptionError.
    """
    monkeypatch.delenv("AION_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AION_ENV", "production")

    with pytest.raises(CredentialDecryptionError):
        _get_encryption_key()


def test_invalid_hex_key_in_production_raises(monkeypatch):
    """Chiave non-hex in produzione -> CredentialDecryptionError."""
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", "not-hex-at-all")
    monkeypatch.setenv("AION_ENV", "production")

    with pytest.raises(CredentialDecryptionError):
        _get_encryption_key()


def test_wrong_length_key_in_production_raises(monkeypatch):
    """Chiave hex con lunghezza non valida (non 16/24/32 byte) -> CredentialDecryptionError."""
    # 10 byte = 20 char hex, non valido
    monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(10).hex())
    monkeypatch.setenv("AION_ENV", "production")

    with pytest.raises(CredentialDecryptionError):
        _get_encryption_key()


# ---------------------------------------------------------------------------
# 6. Chiave mancante in dev -> fallback sicuro
# ---------------------------------------------------------------------------


def test_missing_key_in_dev_uses_fallback(monkeypatch):
    """Con AION_ENV=dev e nessuna chiave, usa la chiave di sviluppo (32 byte)."""
    monkeypatch.delenv("AION_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AION_ENV", "dev")

    key = _get_encryption_key()
    assert isinstance(key, bytes)
    assert len(key) == 32


def test_missing_key_in_local_uses_fallback(monkeypatch):
    """AION_ENV=local e' considerato env di sviluppo: usa il fallback."""
    monkeypatch.delenv("AION_CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AION_ENV", "local")

    key = _get_encryption_key()
    assert len(key) == 32


def test_valid_key_all_lengths(monkeypatch):
    """16, 24 e 32 byte in hex sono tutti accettati."""
    monkeypatch.delenv("AION_ENV", raising=False)
    for nbytes in (16, 24, 32):
        monkeypatch.setenv("AION_CREDENTIAL_ENCRYPTION_KEY", os.urandom(nbytes).hex())
        key = _get_encryption_key()
        assert len(key) == nbytes
