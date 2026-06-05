"""Tests for public embed endpoint behavior after service extraction."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.router import api_router
from app.services.ai.openai_credentials import OpenAICredentialContext


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_test_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
def agent() -> MagicMock:
    """Build a minimal active public embed agent."""
    embed_agent = MagicMock()
    embed_agent.id = uuid.uuid4()
    embed_agent.workspace_id = uuid.uuid4()
    embed_agent.public_id = "demo-public-id"
    embed_agent.name = "Demo Agent"
    embed_agent.system_prompt = "You are helpful."
    embed_agent.voice_id = "ash"
    embed_agent.language = "en-US"
    embed_agent.initial_greeting = "Hello from the widget"
    embed_agent.channel_mode = "both"
    embed_agent.allowed_domains = ["allowed.example"]
    embed_agent.embed_settings = {
        "button_text": "Chat now",
        "theme": "light",
        "position": "bottom-left",
        "primary_color": "#123456",
    }
    embed_agent.text_max_context_messages = 1
    embed_agent.temperature = 0.4
    embed_agent.max_tokens = 123
    embed_agent.turn_detection_mode = "server_vad"
    embed_agent.turn_detection_threshold = 0.6
    embed_agent.silence_duration_ms = 800
    return embed_agent


@pytest.fixture
def patched_agent(agent: MagicMock) -> AsyncIterator[MagicMock]:
    with patch(
        "app.services.embed.service.PublicEmbedService.get_agent_by_public_id",
        new=AsyncMock(return_value=agent),
    ):
        yield agent


def _openai_context() -> OpenAICredentialContext:
    return OpenAICredentialContext(bearer_token="sk-test", source="test")


def _fake_http_client(json_payload: dict[str, object], status_code: int = 200) -> AsyncMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_payload

    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    return client


class TestEmbedOriginValidation:
    async def test_config_allows_configured_origin(
        self,
        client: AsyncClient,
        patched_agent: MagicMock,
    ) -> None:
        del patched_agent

        response = await client.get(
            "/api/v1/p/embed/demo-public-id/config",
            headers={"Origin": "https://allowed.example"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "public_id": "demo-public-id",
            "name": "Demo Agent",
            "greeting_message": "Hello from the widget",
            "button_text": "Chat now",
            "theme": "light",
            "position": "bottom-left",
            "primary_color": "#123456",
            "language": "en-US",
            "voice": "ash",
            "channel_mode": "both",
        }

    async def test_config_blocks_unconfigured_origin(
        self,
        client: AsyncClient,
        patched_agent: MagicMock,
    ) -> None:
        del patched_agent

        response = await client.get(
            "/api/v1/p/embed/demo-public-id/config",
            headers={"Origin": "https://evil.example"},
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Origin not allowed"


class TestEmbedChatAndVoiceFlows:
    async def test_chat_flow_sends_trimmed_history_to_openai(
        self,
        client: AsyncClient,
        patched_agent: MagicMock,
    ) -> None:
        del patched_agent
        fake_http_client = _fake_http_client(
            {"choices": [{"message": {"content": "Sure, I can help."}}]}
        )

        with (
            patch(
                "app.services.embed.access.enforce_chat_rate_limits",
                new=AsyncMock(),
            ),
            patch(
                "app.services.embed.openai.resolve_openai_credentials",
                new=AsyncMock(return_value=_openai_context()),
            ),
            patch(
                "app.services.embed.openai.httpx.AsyncClient",
                return_value=fake_http_client,
            ),
        ):
            response = await client.post(
                "/api/v1/p/embed/demo-public-id/chat",
                headers={"Origin": "https://allowed.example"},
                json={
                    "message": "Can you help?",
                    "conversation_history": [
                        {"role": "user", "content": "old message"},
                        {"role": "assistant", "content": "recent answer"},
                    ],
                },
            )

        assert response.status_code == 200
        assert response.json() == {"response": "Sure, I can help.", "tool_calls": []}

        post_args = fake_http_client.post.await_args
        assert post_args.args[0] == "https://api.openai.com/v1/chat/completions"
        payload = post_args.kwargs["json"]
        assert payload["model"] == "gpt-5.4-nano"
        assert payload["temperature"] == 0.4
        assert payload["max_completion_tokens"] == 123
        assert payload["messages"] == [
            {"role": "system", "content": "You are helpful."},
            {"role": "assistant", "content": "recent answer"},
            {"role": "user", "content": "Can you help?"},
        ]

    async def test_chat_flow_forwards_image_part_to_openai(
        self,
        client: AsyncClient,
        patched_agent: MagicMock,
    ) -> None:
        del patched_agent
        data_url = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        fake_http_client = _fake_http_client(
            {"choices": [{"message": {"content": "Based on the photo, the flashing is cracked."}}]}
        )

        with (
            patch(
                "app.services.embed.access.enforce_chat_rate_limits",
                new=AsyncMock(),
            ),
            patch(
                "app.services.embed.openai.resolve_openai_credentials",
                new=AsyncMock(return_value=_openai_context()),
            ),
            patch(
                "app.services.embed.openai.httpx.AsyncClient",
                return_value=fake_http_client,
            ),
        ):
            response = await client.post(
                "/api/v1/p/embed/demo-public-id/chat",
                headers={"Origin": "https://allowed.example"},
                json={
                    "message": "What is wrong with this roof?",
                    "conversation_history": [],
                    "image": data_url,
                },
            )

        assert response.status_code == 200
        payload = fake_http_client.post.await_args.kwargs["json"]
        assert payload["messages"][-1] == {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is wrong with this roof?"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }

    async def test_chat_flow_rejects_invalid_image(
        self,
        client: AsyncClient,
        patched_agent: MagicMock,
    ) -> None:
        del patched_agent

        with patch(
            "app.services.embed.access.enforce_chat_rate_limits",
            new=AsyncMock(),
        ):
            response = await client.post(
                "/api/v1/p/embed/demo-public-id/chat",
                headers={"Origin": "https://allowed.example"},
                json={
                    "message": "look at this",
                    "conversation_history": [],
                    "image": "data:application/pdf;base64,Zm9v",
                },
            )

        assert response.status_code == 422

    async def test_voice_flow_mints_realtime_client_secret(
        self,
        client: AsyncClient,
        patched_agent: MagicMock,
    ) -> None:
        del patched_agent
        fake_http_client = _fake_http_client({"client_secret": {"value": "voice-secret"}})

        with (
            patch(
                "app.services.embed.access.enforce_token_rate_limits",
                new=AsyncMock(),
            ),
            patch(
                "app.services.embed.openai.resolve_openai_credentials",
                new=AsyncMock(return_value=_openai_context()),
            ),
            patch(
                "app.services.embed.openai.httpx.AsyncClient",
                return_value=fake_http_client,
            ),
        ):
            response = await client.post(
                "/api/v1/p/embed/demo-public-id/token",
                headers={"Origin": "https://allowed.example"},
                json={"mode": "voice"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["client_secret"] == {"value": "voice-secret"}
        assert data["agent"] == {
            "name": "Demo Agent",
            "voice": "ash",
            "language": "en-US",
            "initial_greeting": "Hello from the widget",
        }
        assert data["tools"][0]["name"] == "end_call"

        post_args = fake_http_client.post.await_args
        assert post_args.args[0] == "https://api.openai.com/v1/realtime/client_secrets"
        payload = post_args.kwargs["json"]
        session = payload["session"]
        assert session["type"] == "realtime"
        assert session["instructions"] == "You are helpful."
        assert session["output_modalities"] == ["audio"]
        assert session["audio"]["output"]["voice"] == "ash"
        assert session["audio"]["input"]["turn_detection"]["threshold"] == 0.6
