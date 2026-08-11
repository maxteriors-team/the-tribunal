"""Tests for application settings validation."""

import os

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_SECRET_KEY = "s" * 32
_STORAGE_ENV = {
    "MMS_STORAGE_BUCKET": "crm-media-test",
    "MMS_STORAGE_ENDPOINT_URL": "https://storage.railway.app",
    "MMS_STORAGE_ACCESS_KEY_ID": "test-access-key",
    "MMS_STORAGE_SECRET_ACCESS_KEY": "test-secret-key",
    "MMS_STORAGE_REGION": "auto",
}


@pytest.fixture(autouse=True)
def _clear_mms_storage_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep developer/CI storage credentials from influencing these tests."""
    for name in tuple(os.environ):
        if name.startswith("MMS_STORAGE_"):
            monkeypatch.delenv(name)


def _settings(**overrides: object) -> Settings:
    return Settings(secret_key=_SECRET_KEY, _env_file=None, **overrides)  # type: ignore[arg-type]


def test_mms_storage_is_disabled_by_default() -> None:
    configured = _settings()

    assert configured.mms_storage_enabled is False
    assert configured.mms_storage_presign_ttl_seconds == 300
    assert configured.mms_storage_max_download_bytes == 10 * 1024 * 1024
    assert configured.mms_storage_addressing_style == "virtual"


def test_mms_storage_loads_complete_railway_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in _STORAGE_ENV.items():
        monkeypatch.setenv(name, value)

    configured = _settings()

    assert configured.mms_storage_enabled is True
    assert configured.mms_storage_bucket == "crm-media-test"
    assert configured.mms_storage_endpoint_url == "https://storage.railway.app"
    assert configured.mms_storage_access_key_id == "test-access-key"
    assert configured.mms_storage_secret_access_key.get_secret_value() == "test-secret-key"
    assert "test-secret-key" not in repr(configured)


def test_mms_storage_rejects_partial_configuration() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(
            mms_storage_bucket="crm-media-test",
            mms_storage_secret_access_key="do-not-leak-this-secret",
        )

    message = str(exc_info.value)
    assert "MMS storage configuration is incomplete" in message
    assert "MMS_STORAGE_ACCESS_KEY_ID" in message
    assert "MMS_STORAGE_ENDPOINT_URL" in message
    assert "do-not-leak-this-secret" not in message


@pytest.mark.parametrize(
    "endpoint",
    [
        "storage.railway.app",
        "ftp://storage.railway.app",
        "https://user:password@storage.railway.app",
        "https://storage.railway.app?token=secret",
        "https://storage.railway.app#fragment",
    ],
)
def test_mms_storage_rejects_unsafe_endpoint(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="must be an HTTP\\(S\\) base URL"):
        _settings(
            mms_storage_bucket="crm-media-test",
            mms_storage_endpoint_url=endpoint,
            mms_storage_access_key_id="test-access-key",
            mms_storage_secret_access_key="test-secret-key",
        )


def test_mms_storage_requires_https_in_deployed_environments() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        _settings(
            environment="production",
            mms_storage_bucket="crm-media-test",
            mms_storage_endpoint_url="http://minio.internal:9000",
            mms_storage_access_key_id="test-access-key",
            mms_storage_secret_access_key="test-secret-key",
        )


def test_mms_storage_allows_http_for_local_emulators() -> None:
    configured = _settings(
        environment="test",
        mms_storage_bucket="crm-media-test",
        mms_storage_endpoint_url="http://minio:9000",
        mms_storage_access_key_id="test-access-key",
        mms_storage_secret_access_key="test-secret-key",
        mms_storage_addressing_style="path",
    )

    assert configured.mms_storage_enabled is True
    assert configured.mms_storage_addressing_style == "path"
