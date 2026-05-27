"""Tests for encryption helpers."""

import pytest
from cryptography.fernet import InvalidToken

from app.core.encryption import EncryptedString, decrypt_json, encrypt_json


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
