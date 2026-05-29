"""Tests for embed endpoint rate limiting.

Verifies that the public embed routes return HTTP 429 once the per-IP /
per-public_id Redis-backed counters are exhausted. The tests stub the agent
lookup, origin validation, and the OpenAI HTTP calls so the routes can be
exercised without a database, Redis, or network.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
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


def _build_agent_mock() -> MagicMock:
    """Build a minimal Agent mock sufficient for embed endpoints."""
    agent = MagicMock()
    agent.id = "agent-id"
    agent.workspace_id = uuid.uuid4()
    agent.public_id = "demo-public-id"
    agent.name = "Test Agent"
    agent.system_prompt = "be helpful"
    agent.voice_id = "ash"
    agent.language = "en"
    agent.initial_greeting = "hi"
    agent.channel_mode = "voice"
    agent.allowed_domains = []
    agent.embed_settings = {}
    agent.text_max_context_messages = 8
    agent.temperature = 0.7
    agent.max_tokens = 512
    agent.enabled_tools = []
    return agent


@pytest.fixture
def patched_agent() -> AsyncIterator[MagicMock]:
    """Patch ``get_agent_by_public_id`` to return a ready-to-use agent mock."""
    agent = _build_agent_mock()
    with patch(
        "app.api.v1.embed.get_agent_by_public_id",
        new=AsyncMock(return_value=agent),
    ):
        yield agent


@pytest.fixture
def allow_origin() -> AsyncIterator[MagicMock]:
    with patch("app.api.v1.embed.validate_origin", return_value=True) as patched:
        yield patched


class TestTokenEndpointRateLimit:
    """``POST /p/embed/{public_id}/token`` — 10 requests / hour / IP."""

    async def test_token_returns_429_after_per_ip_limit(
        self, client: AsyncClient, patched_agent: MagicMock, allow_origin: MagicMock
    ) -> None:
        """After 10 successful token mints, the 11th from the same IP is 429."""
        del patched_agent, allow_origin  # fixtures applied via side effects

        counts: dict[str, int] = {}
        limit = 10

        async def fake_token_limits(client_ip: str, public_id: str) -> None:
            del public_id
            current = counts.get(client_ip, 0)
            if current >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later.",
                )
            counts[client_ip] = current + 1

        # Stub OpenAI HTTP call so the endpoint succeeds when not limited.
        fake_openai_response = MagicMock()
        fake_openai_response.status_code = 200
        fake_openai_response.json.return_value = {"value": "ephemeral-secret"}

        fake_http_client = AsyncMock()
        fake_http_client.post = AsyncMock(return_value=fake_openai_response)
        fake_http_client.__aenter__.return_value = fake_http_client
        fake_http_client.__aexit__.return_value = None

        with (
            patch(
                "app.api.v1.embed.enforce_token_rate_limits",
                side_effect=fake_token_limits,
            ),
            patch(
                "app.api.v1.embed.resolve_openai_credentials",
                new=AsyncMock(
                    return_value=OpenAICredentialContext(
                        bearer_token="sk-test",
                        source="test",
                    )
                ),
            ),
            patch(
                "app.api.v1.embed.httpx.AsyncClient",
                return_value=fake_http_client,
            ),
        ):
            for i in range(limit):
                resp = await client.post(
                    "/api/v1/p/embed/demo-public-id/token",
                    json={"mode": "voice"},
                )
                assert resp.status_code == 200, (
                    f"request {i + 1} should succeed, got {resp.status_code}"
                )
                if i == 0:
                    assert "instructions" not in resp.json()["agent"]

            resp = await client.post(
                "/api/v1/p/embed/demo-public-id/token",
                json={"mode": "voice"},
            )

        first_post = fake_http_client.post.await_args_list[0].kwargs
        body = first_post["json"]
        assert "session" in body
        assert body["session"]["type"] == "realtime"
        assert body["session"]["output_modalities"] == ["audio"]
        assert body["session"]["audio"]["input"]["format"] == {"type": "audio/pcmu"}
        assert resp.status_code == 429
        assert resp.json()["detail"] == "Rate limit exceeded. Please try again later."


class TestChatEndpointRateLimit:
    """``POST /p/embed/{public_id}/chat`` — 60 msgs / hour / public_id."""

    async def test_chat_returns_429_after_per_public_id_limit(
        self, client: AsyncClient, patched_agent: MagicMock, allow_origin: MagicMock
    ) -> None:
        del patched_agent, allow_origin

        counts: dict[str, int] = {}
        limit = 60

        async def fake_chat_limits(client_ip: str, public_id: str) -> None:
            del client_ip
            current = counts.get(public_id, 0)
            if current >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later.",
                )
            counts[public_id] = current + 1

        fake_openai_response = MagicMock()
        fake_openai_response.status_code = 200
        fake_openai_response.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
        fake_http_client = AsyncMock()
        fake_http_client.post = AsyncMock(return_value=fake_openai_response)
        fake_http_client.__aenter__.return_value = fake_http_client
        fake_http_client.__aexit__.return_value = None

        with (
            patch(
                "app.api.v1.embed.enforce_chat_rate_limits",
                side_effect=fake_chat_limits,
            ),
            patch(
                "app.api.v1.embed.resolve_openai_credentials",
                new=AsyncMock(
                    return_value=OpenAICredentialContext(
                        bearer_token="sk-test",
                        source="test",
                    )
                ),
            ),
            patch(
                "app.api.v1.embed.httpx.AsyncClient",
                return_value=fake_http_client,
            ),
        ):
            for i in range(limit):
                resp = await client.post(
                    "/api/v1/p/embed/demo-public-id/chat",
                    json={"message": "hi", "conversation_history": []},
                )
                assert resp.status_code == 200, (
                    f"request {i + 1} should succeed, got {resp.status_code}"
                )

            resp = await client.post(
                "/api/v1/p/embed/demo-public-id/chat",
                json={"message": "hi", "conversation_history": []},
            )

        assert resp.status_code == 429

    async def test_tool_call_uses_chat_limits(
        self, client: AsyncClient, patched_agent: MagicMock, allow_origin: MagicMock
    ) -> None:
        """``/tool-call`` shares the chat budget and returns 429 once exceeded."""
        del patched_agent, allow_origin

        async def always_block(**_: object) -> None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
            )

        with patch(
            "app.api.v1.embed.enforce_chat_rate_limits",
            side_effect=always_block,
        ):
            resp = await client.post(
                "/api/v1/p/embed/demo-public-id/tool-call",
                json={"tool_name": "end_call", "arguments": {}},
            )

        assert resp.status_code == 429

    async def test_transcript_uses_chat_limits(
        self, client: AsyncClient, patched_agent: MagicMock, allow_origin: MagicMock
    ) -> None:
        """``/transcript`` shares the chat budget and returns 429 once exceeded."""
        del patched_agent, allow_origin

        async def always_block(**_: object) -> None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
            )

        with patch(
            "app.api.v1.embed.enforce_chat_rate_limits",
            side_effect=always_block,
        ):
            resp = await client.post(
                "/api/v1/p/embed/demo-public-id/transcript",
                json={
                    "session_id": "sess",
                    "transcript": "hello",
                    "duration_seconds": 5,
                },
            )

        assert resp.status_code == 429


class TestEmbedLimiterUnit:
    """Direct tests for the limiter helper to confirm 429 raising behavior."""

    async def test_enforce_embed_rate_limit_raises_when_disallowed(self) -> None:
        from app.services.rate_limiting import embed_limiter

        async def fake_check(
            scope: str,
            identifier: str,
            limit: int,
            window_seconds: int,
        ) -> tuple[bool, int]:
            del scope, identifier, limit, window_seconds
            return False, 999

        with (
            patch.object(embed_limiter, "_check_and_increment", new=fake_check),
            pytest.raises(HTTPException) as exc_info,
        ):
            await embed_limiter.enforce_embed_rate_limit(
                scope="token:ip",
                identifier="1.2.3.4",
                limit=10,
                window_seconds=3600,
            )

        assert exc_info.value.status_code == 429

    async def test_enforce_embed_rate_limit_fails_open_on_redis_error(self) -> None:
        from app.services.rate_limiting import embed_limiter

        async def boom(**_: object) -> tuple[bool, int]:
            raise RuntimeError("redis down")

        with patch.object(embed_limiter, "_check_and_increment", new=boom):
            # Must NOT raise — fail-open keeps the endpoint working in outages.
            await embed_limiter.enforce_embed_rate_limit(
                scope="token:ip",
                identifier="1.2.3.4",
                limit=10,
                window_seconds=3600,
            )
