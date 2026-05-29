"""Tests for OpenAI voice session credential wiring."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.core.config import settings
from app.core.encryption import encrypt_json
from app.models.workspace import WorkspaceIntegration
from app.services.ai.voice_agent import OPENAI_REALTIME_CLIENT_SECRETS_URL, VoiceAgentSession
from app.services.ai.voice_session_factory import VoiceSessionFactory


class _ScalarResult:
    def __init__(self, row: Any | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any | None:
        return self._row


class _AsyncDB:
    def __init__(self, integration: WorkspaceIntegration | None) -> None:
        self.execute = AsyncMock(return_value=_ScalarResult(integration))
        self.commit = AsyncMock()


def _workspace_integration(credentials: dict[str, Any]) -> WorkspaceIntegration:
    return WorkspaceIntegration(
        workspace_id=uuid.uuid4(),
        integration_type="openai",
        encrypted_credentials=encrypt_json(credentials),
        is_active=True,
    )


async def test_workspace_oauth_voice_session_uses_realtime_client_secret() -> None:
    integration = _workspace_integration(
        {
            "access_token": "oauth-access-token",
            "refresh_token": "oauth-refresh-token",
            "expires_at": 4_102_444_800_000,
            "account_id": "acct_123",
        }
    )
    db = _AsyncDB(integration)

    session, error = await VoiceSessionFactory(settings).create_session_for_workspace(
        db,
        integration.workspace_id,
        "openai",
    )

    assert error is None
    assert session is not None
    assert session.api_key == "oauth-access-token"
    assert session.use_client_secret is True
    assert session.credential_source == "workspace_oauth"
    assert session.additional_headers == {
        "chatgpt-account-id": "acct_123",
        "originator": "the-tribunal",
    }


async def test_oauth_voice_session_mints_client_secret_before_websocket_connect() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"value": "ek-ephemeral"})

    original_async_client = httpx.AsyncClient

    def mock_async_client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["timeout"] == 30.0
        return original_async_client(transport=httpx.MockTransport(handler))

    fake_ws = MagicMock()
    fake_ws.send = AsyncMock()
    session = VoiceAgentSession(
        "oauth-access-token",
        additional_headers={"chatgpt-account-id": "acct_123", "originator": "the-tribunal"},
        use_client_secret=True,
        credential_source="workspace_oauth",
    )

    with (
        patch("app.services.ai.voice_agent.httpx.AsyncClient", mock_async_client),
        patch(
            "app.services.ai.voice_agent.connect",
            new=AsyncMock(return_value=fake_ws),
        ) as connect_mock,
    ):
        connected = await session.connect()

    assert connected is True
    assert captured_requests[0].url == httpx.URL(OPENAI_REALTIME_CLIENT_SECRETS_URL)
    assert captured_requests[0].headers["Authorization"] == "Bearer oauth-access-token"
    assert captured_requests[0].headers["chatgpt-account-id"] == "acct_123"
    connect_headers = connect_mock.await_args.kwargs["additional_headers"]
    assert connect_headers == {"Authorization": "Bearer ek-ephemeral"}


async def test_workspace_api_key_voice_session_uses_direct_realtime_auth() -> None:
    integration = _workspace_integration({"api_key": "sk-workspace"})
    db = _AsyncDB(integration)

    session, error = await VoiceSessionFactory(settings).create_session_for_workspace(
        db,
        integration.workspace_id,
        "openai",
    )

    assert error is None
    assert session is not None
    assert session.api_key == "sk-workspace"
    assert session.use_client_secret is False
    assert session.credential_source == "workspace_api_key"
    assert session.additional_headers == {}
