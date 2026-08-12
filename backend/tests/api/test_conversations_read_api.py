"""Tests for the conversation unread rollup and mark-as-read endpoints.

Route wiring, auth, and response shape are exercised against a mocked service.
The service methods themselves are covered in
``tests/services/conversations/test_conversation_read_state.py``.

The route-ordering test is the load-bearing one: ``GET /unread`` is declared
before ``GET /{conversation_id}``, and reversing that order turns the rollup
into a 422 (``"unread"`` is not a UUID).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import conversations as conversations_module
from app.schemas.conversation import (
    ConversationResponse,
    MarkAllReadResponse,
    UnreadSummary,
)

WS_ID = uuid.uuid4()
CONV_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_auth_test_app(mock_db: AsyncMock) -> FastAPI:
    """Create a test app with auth + workspace dependencies overridden."""
    app = FastAPI(lifespan=_test_lifespan)

    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True

    user = MagicMock()
    user.id = 1
    user.is_active = True

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return ws

    async def override_get_current_user() -> MagicMock:
        return user

    async def override_get_membership() -> MagicMock:
        membership = MagicMock()
        membership.role = "owner"
        membership.workspace_id = WS_ID
        membership.user_id = user.id
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = override_get_membership

    app.include_router(
        conversations_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/conversations",
    )
    return app


def _make_noauth_test_app() -> FastAPI:
    """Create a test app without dependency overrides (auth will fail)."""
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(
        conversations_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/conversations",
    )
    return app


def _conversation_response(unread_count: int = 0) -> ConversationResponse:
    return ConversationResponse(
        id=CONV_ID,
        workspace_id=WS_ID,
        contact_id=42,
        contact_name="Robin Stevanovich",
        workspace_phone="+15550000000",
        contact_phone="+15551234567",
        status="active",
        channel="sms",
        assigned_agent_id=None,
        ai_enabled=True,
        ai_paused=False,
        unread_count=unread_count,
        last_message_preview="On my way",
        last_message_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
async def client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    app = _make_auth_test_app(mock_db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    app = _make_noauth_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestUnreadSummaryEndpoint:
    """GET /conversations/unread backs the header chat badge."""

    async def test_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/conversations/unread")
        assert response.status_code == 401

    async def test_returns_rollup(self, client: AsyncClient) -> None:
        summary = UnreadSummary(unread_conversations=3, unread_messages=7)
        with patch.object(
            conversations_module.ConversationService,
            "get_unread_summary",
            new=AsyncMock(return_value=summary),
        ):
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/conversations/unread")

        assert response.status_code == 200
        assert response.json() == {"unread_conversations": 3, "unread_messages": 7}

    async def test_not_swallowed_by_conversation_id_route(self, client: AsyncClient) -> None:
        """``/unread`` must not be parsed as a conversation UUID (422 regression)."""
        get_conversation = AsyncMock()
        with (
            patch.object(
                conversations_module.ConversationService,
                "get_unread_summary",
                new=AsyncMock(
                    return_value=UnreadSummary(
                        unread_conversations=0, unread_messages=0
                    )
                ),
            ),
            patch.object(
                conversations_module.ConversationService,
                "get_conversation",
                new=get_conversation,
            ),
        ):
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/conversations/unread")

        assert response.status_code == 200
        get_conversation.assert_not_awaited()

    async def test_scopes_to_workspace(self, client: AsyncClient) -> None:
        summary_mock = AsyncMock(
            return_value=UnreadSummary(unread_conversations=0, unread_messages=0)
        )
        with patch.object(
            conversations_module.ConversationService,
            "get_unread_summary",
            new=summary_mock,
        ):
            await client.get(f"/api/v1/workspaces/{WS_ID}/conversations/unread")

        assert summary_mock.call_args.kwargs["workspace_id"] == WS_ID


class TestMarkConversationReadEndpoint:
    """POST /conversations/{id}/read clears one thread."""

    async def test_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/conversations/{CONV_ID}/read"
        )
        assert response.status_code == 401

    async def test_returns_updated_conversation(self, client: AsyncClient) -> None:
        with patch.object(
            conversations_module.ConversationService,
            "mark_read",
            new=AsyncMock(return_value=_conversation_response(unread_count=0)),
        ):
            response = await client.post(
                f"/api/v1/workspaces/{WS_ID}/conversations/{CONV_ID}/read"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(CONV_ID)
        assert body["unread_count"] == 0
        assert body["contact_name"] == "Robin Stevanovich"

    async def test_delegates_scoped_ids(self, client: AsyncClient) -> None:
        mark_read = AsyncMock(return_value=_conversation_response())
        with patch.object(
            conversations_module.ConversationService, "mark_read", new=mark_read
        ):
            await client.post(f"/api/v1/workspaces/{WS_ID}/conversations/{CONV_ID}/read")

        assert mark_read.call_args.kwargs["conversation_id"] == CONV_ID
        assert mark_read.call_args.kwargs["workspace_id"] == WS_ID


class TestMarkAllReadEndpoint:
    """POST /conversations/read clears the whole workspace."""

    async def test_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(f"/api/v1/workspaces/{WS_ID}/conversations/read")
        assert response.status_code == 401

    async def test_returns_marked_count(self, client: AsyncClient) -> None:
        with patch.object(
            conversations_module.ConversationService,
            "mark_all_read",
            new=AsyncMock(return_value=MarkAllReadResponse(conversations_marked=4)),
        ):
            response = await client.post(f"/api/v1/workspaces/{WS_ID}/conversations/read")

        assert response.status_code == 200
        assert response.json() == {"conversations_marked": 4}

    async def test_does_not_hit_the_send_message_route(self, client: AsyncClient) -> None:
        """``/read`` is a static sibling of ``/{conversation_id}``, not a thread id."""
        send_message = AsyncMock()
        with (
            patch.object(
                conversations_module.ConversationService,
                "mark_all_read",
                new=AsyncMock(return_value=MarkAllReadResponse(conversations_marked=0)),
            ),
            patch.object(
                conversations_module.ConversationService, "send_message", new=send_message
            ),
        ):
            response = await client.post(f"/api/v1/workspaces/{WS_ID}/conversations/read")

        assert response.status_code == 200
        send_message.assert_not_awaited()
