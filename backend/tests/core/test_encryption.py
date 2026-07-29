"""Tests for encryption helpers."""

import pytest
from cryptography.fernet import InvalidToken

from app.core.encryption import (
    EncryptedString,
    _derive_fernet_key,
    decrypt_json,
    encrypt_json,
)


def test_encrypted_string_round_trips_ciphertext() -> None:
    encrypted_string = EncryptedString()

    stored = encrypted_string.process_bind_param("user@example.com", dialect=None)  # type: ignore[arg-type]
    assert stored is not None
    assert stored != "user@example.com"

    assert encrypted_string.process_result_value(stored, dialect=None) == "user@example.com"  # type: ignore[arg-type]


def test_encrypted_string_reads_legacy_plaintext() -> None:
    encrypted_string = EncryptedString()

    actual = encrypted_string.process_result_value("legacy@example.com", dialect=None)  # type: ignore[arg-type]

    assert actual == "legacy@example.com"


def test_encrypted_string_rejects_tampered_fernet_like_token() -> None:
    encrypted_string = EncryptedString()

    with pytest.raises(InvalidToken):
        encrypted_string.process_result_value("gAAAAA-invalid-token", dialect=None)  # type: ignore[arg-type]


def test_decrypt_json_round_trips_ciphertext() -> None:
    stored = encrypt_json({"api_key": "sk-test"})

    assert decrypt_json(stored) == {"api_key": "sk-test"}


def test_decrypt_json_reads_legacy_plaintext_json_object() -> None:
    assert decrypt_json('{"api_key":"sk-legacy"}') == {"api_key": "sk-legacy"}


def test_decrypt_json_reads_legacy_jsonb_dict() -> None:
    assert decrypt_json({"api_key": "sk-legacy"}) == {"api_key": "sk-legacy"}


def test_decrypt_json_rejects_tampered_fernet_like_token() -> None:
    with pytest.raises(InvalidToken):
        decrypt_json("gAAAAA-invalid-token")


def test_key_derivation_is_cached_so_bulk_decrypt_stays_off_the_hot_path() -> None:
    """Guard the fix for a production event-loop stall.

    ``_derive_fernet_key`` runs PBKDF2 at 310,000 iterations (~95ms). It sits on
    the path of every encrypt and decrypt, so once conversation, message, and
    contact PII moved under ``EncryptedString`` an uncached derivation ran once
    per row per encrypted column -- a single 100-row contacts page burned ~28s of
    CPU inside the event loop, stalling unrelated requests and every background
    worker in the process.

    Asserting on the cache rather than on wall-clock keeps this deterministic on
    a loaded CI box.
    """
    _derive_fernet_key.cache_clear()
    encrypted_string = EncryptedString()

    stored = encrypted_string.process_bind_param("+15551234567", dialect=None)  # type: ignore[arg-type]
    assert stored is not None
    for _ in range(50):
        assert encrypted_string.process_result_value(stored, dialect=None) == "+15551234567"  # type: ignore[arg-type]

    info = _derive_fernet_key.cache_info()
    assert info.misses == 1, "key must be derived once, not once per decrypt"
    assert info.hits >= 50


def test_cached_key_derivation_still_returns_the_real_key() -> None:
    """Caching must not change the derived key -- that would orphan ciphertext."""
    _derive_fernet_key.cache_clear()
    cold = _derive_fernet_key("a-secret-value-for-derivation")
    warm = _derive_fernet_key("a-secret-value-for-derivation")

    assert cold == warm
    assert _derive_fernet_key("a-different-secret") != cold
