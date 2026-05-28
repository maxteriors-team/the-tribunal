"""Tests for OpenAI Codex OAuth workspace integration helpers."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import settings
from app.core.encryption import encrypt_json
from app.models.workspace import WorkspaceIntegration
from app.services.ai import openai_oauth
from app.services.ai.openai_oauth import (
    DEFAULT_OPENAI_OAUTH_CLIENT_ID,
    OPENAI_OAUTH_AUTHORIZE_URL,
    build_openai_oauth_start,
    disconnect_openai_oauth,
    get_openai_oauth_status,
)


class _ScalarResult:
    def __init__(self, row: Any | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any | None:
        return self._row


class _AsyncDB:
    def __init__(self, integration: WorkspaceIntegration | None) -> None:
        self.integration = integration
        self.execute = AsyncMock(return_value=_ScalarResult(integration))
        self.commit = AsyncMock()
        self.delete = AsyncMock()


def _workspace_integration(credentials: dict[str, Any]) -> WorkspaceIntegration:
    return WorkspaceIntegration(
        workspace_id=uuid.uuid4(),
        integration_type="openai",
        encrypted_credentials=encrypt_json(credentials),
        is_active=True,
    )


@pytest.fixture(autouse=True)
def _reset_openai_oauth_settings() -> None:
    settings.openai_oauth_client_id = ""
    settings.openai_oauth_redirect_uri = ""
    settings.openai_api_key = ""
    settings.api_base_url = ""
    settings.public_base_url = "http://localhost:8000"


async def test_build_openai_oauth_start_uses_codex_client_and_encrypted_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    user_id = 123
    monkeypatch.setattr(
        openai_oauth,
        "ensure_local_openai_oauth_callback_server",
        lambda: "http://localhost:1455/auth/callback",
    )

    start = build_openai_oauth_start(workspace_id, user_id)

    parsed = urlparse(start.authorization_url)
    params = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == OPENAI_OAUTH_AUTHORIZE_URL
    assert params["client_id"] == [DEFAULT_OPENAI_OAUTH_CLIENT_ID]
    assert params["redirect_uri"] == ["http://localhost:1455/auth/callback"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["codex_cli_simplified_flow"] == ["true"]
    assert params["originator"] == ["the-tribunal"]
    assert "code_verifier" not in params

    decoded_state = openai_oauth._decode_state(params["state"][0])  # noqa: SLF001
    assert decoded_state.workspace_id == workspace_id
    assert decoded_state.user_id == user_id
    assert decoded_state.client_id == DEFAULT_OPENAI_OAUTH_CLIENT_ID
    assert decoded_state.redirect_uri == "http://localhost:1455/auth/callback"
    assert decoded_state.code_verifier


async def test_build_openai_oauth_start_uses_hosted_callback_when_api_base_url_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    user_id = 123
    settings.api_base_url = "https://api.thetribunal.ai/"
    monkeypatch.setattr(
        openai_oauth,
        "ensure_local_openai_oauth_callback_server",
        lambda: pytest.fail("localhost callback should not be started for hosted URL"),
    )

    start = build_openai_oauth_start(workspace_id, user_id)

    parsed = urlparse(start.authorization_url)
    params = parse_qs(parsed.query)
    callback_url = "https://api.thetribunal.ai/api/v1/integrations/openai/oauth/callback"
    assert params["redirect_uri"] == [callback_url]
    decoded_state = openai_oauth._decode_state(params["state"][0])  # noqa: SLF001
    assert decoded_state.redirect_uri == callback_url


async def test_get_openai_oauth_status_reports_safe_snapshot() -> None:
    integration = _workspace_integration(
        {
            "access_token": "secret-access-token",
            "refresh_token": "secret-refresh-token",
            "expires_at": 1_800_000_000_000,
            "account_id": "acct_123",
            "email": "owner@example.com",
            "auth_method": "chatgpt_subscription",
            "chatgpt_plan_type": "plus",
            "last_oauth_login_at": "2026-05-28T10:00:00+00:00",
            "api_key": "sk-fallback",
        }
    )
    db = _AsyncDB(integration)

    status = await get_openai_oauth_status(db, integration.workspace_id)

    assert status.connected is True
    assert status.account_id == "acct_123"
    assert status.email == "owner@example.com"
    assert status.expires_at == 1_800_000_000_000
    assert status.auth_method == "chatgpt_subscription"
    assert status.plan_type == "plus"
    assert status.api_key_configured is True
    assert "secret" not in repr(status)


async def test_disconnect_openai_oauth_preserves_api_key_credentials() -> None:
    integration = _workspace_integration(
        {
            "access_token": "secret-access-token",
            "refresh_token": "secret-refresh-token",
            "expires_at": 1_800_000_000_000,
            "account_id": "acct_123",
            "email": "owner@example.com",
            "api_key": "sk-fallback",
            "organization_id": "org_123",
        }
    )
    db = _AsyncDB(integration)

    status = await disconnect_openai_oauth(db, integration.workspace_id)

    assert status.connected is False
    assert status.api_key_configured is True
    assert integration.credentials == {"api_key": "sk-fallback", "organization_id": "org_123"}
    db.delete.assert_not_called()
    db.commit.assert_awaited_once()


async def test_disconnect_openai_oauth_deletes_integration_without_api_key() -> None:
    integration = _workspace_integration(
        {
            "access_token": "secret-access-token",
            "refresh_token": "secret-refresh-token",
            "expires_at": 1_800_000_000_000,
            "account_id": "acct_123",
        }
    )
    db = _AsyncDB(integration)

    status = await disconnect_openai_oauth(db, integration.workspace_id)

    assert status.connected is False
    assert status.api_key_configured is False
    db.delete.assert_awaited_once_with(integration)
    db.commit.assert_awaited_once()
