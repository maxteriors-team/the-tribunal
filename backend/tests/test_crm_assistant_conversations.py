"""Tests for CRM assistant multi-conversation routes."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Select

from app.api.v1 import crm_assistant
from app.models.assistant_conversation import AssistantConversation, AssistantMessage
from app.models.user import User
from app.models.workspace import Workspace


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


def _user(user_id: int = 7) -> User:
    user = User(
        id=user_id,
        email=f"user{user_id}@example.com",
        email_hash=f"email-hash-{user_id}",
        hashed_password="hash",
        is_active=True,
    )
    return user


def _workspace(workspace_id: uuid.UUID) -> Workspace:
    return Workspace(
        id=workspace_id,
        name="Growth Studio",
        slug=f"growth-studio-{workspace_id.hex[:8]}",
        settings={},
        is_active=True,
    )


def _conversation(
    workspace_id: uuid.UUID,
    user_id: int,
    *,
    conversation_id: uuid.UUID | None = None,
    updated_at: datetime | None = None,
) -> AssistantConversation:
    now = datetime(2026, 5, 21, 12, tzinfo=UTC)
    return AssistantConversation(
        id=conversation_id or uuid.uuid4(),
        workspace_id=workspace_id,
        user_id=user_id,
        created_at=now,
        updated_at=updated_at or now,
    )


def _message(
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    *,
    created_at: datetime | None = None,
) -> AssistantMessage:
    return AssistantMessage(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role=role,
        content=content,
        created_at=created_at or datetime(2026, 5, 21, 12, tzinfo=UTC),
    )


def _statement_text(statement: Select[Any]) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": False}))


def _make_db_for_route(
    *,
    conversations: list[AssistantConversation],
    messages: dict[uuid.UUID, list[AssistantMessage]],
) -> MagicMock:
    db = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    def conversation_rows(statement: Select[Any]) -> _ExecuteResult:
        sql = _statement_text(statement)
        if "JOIN" in sql:
            return conversation_list_rows()
        if "assistant_conversations.id =" in sql:
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            return _ExecuteResult(
                [
                    conversation
                    for conversation in conversations
                    if conversation.id.hex in compiled or str(conversation.id) in compiled
                ]
            )
        return _ExecuteResult(conversations[:1])

    def message_rows(statement: Select[Any]) -> _ExecuteResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        return _ExecuteResult(
            [
                row
                for conversation_id, rows in messages.items()
                if conversation_id.hex in compiled or str(conversation_id) in compiled
                for row in rows
            ]
        )

    def conversation_list_rows() -> _ExecuteResult:
        rows: list[tuple[AssistantConversation, int, str | None]] = []
        for conversation in conversations:
            conversation_messages = messages.get(conversation.id, [])
            first_user = next(
                (message.content for message in conversation_messages if message.role == "user"),
                None,
            )
            rows.append((conversation, len(conversation_messages), first_user))
        return _ExecuteResult(rows)

    async def execute(statement: Select[Any]) -> _ExecuteResult:
        sql = _statement_text(statement)
        if "FROM assistant_conversations" in sql:
            return conversation_rows(statement)
        if "FROM assistant_messages" in sql:
            return message_rows(statement)
        return _ExecuteResult([])

    db.execute = AsyncMock(side_effect=execute)
    return db


def _make_stream_app() -> FastAPI:
    app = FastAPI()
    app.include_router(
        crm_assistant.router,
        prefix="/api/v1/workspaces/{workspace_id}/assistant",
    )
    return app


async def _noop_stream(
    *,
    db: Any,
    workspace_id: uuid.UUID,
    user_id: int,
    message: str,
    conversation_id: uuid.UUID | None = None,
    image: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "delta", "text": "Hello"}
    yield {
        "type": "done",
        "conversation_id": str(conversation_id or uuid.uuid4()),
        "message_id": "msg_123",
        "actions_taken": [],
    }


async def test_chat_route_passes_conversation_id_to_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    db = MagicMock()
    current_user = _user()
    workspace = _workspace(workspace_id)
    captured: dict[str, Any] = {}

    async def fake_process(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "response": "Threaded reply",
            "actions_taken": [],
            "conversation_id": str(conversation_id),
        }

    monkeypatch.setattr(crm_assistant, "process_assistant_message", fake_process)

    response = await crm_assistant.chat_with_assistant(
        workspace_id=workspace_id,
        request=crm_assistant.AssistantChatRequest(
            message="Use this thread",
            conversation_id=conversation_id,
        ),
        current_user=current_user,
        db=db,
        workspace=workspace,
    )

    assert captured["conversation_id"] == conversation_id
    assert captured["message"] == "Use this thread"
    assert response.conversation_id == str(conversation_id)


async def test_get_conversation_is_scoped_and_does_not_bleed_messages() -> None:
    workspace_id = uuid.uuid4()
    user_id = 7
    first = _conversation(workspace_id, user_id)
    second = _conversation(workspace_id, user_id)
    db = _make_db_for_route(
        conversations=[second],
        messages={
            first.id: [_message(first.id, "user", "First thread")],
            second.id: [_message(second.id, "user", "Second thread")],
        },
    )

    response = await crm_assistant.get_assistant_conversation(
        workspace_id=workspace_id,
        conversation_id=second.id,
        current_user=_user(user_id),
        db=db,
        workspace=_workspace(workspace_id),
    )

    assert response.id == str(second.id)
    assert [message.content for message in response.messages] == ["Second thread"]


async def test_list_and_delete_conversations_are_scoped() -> None:
    workspace_id = uuid.uuid4()
    user_id = 7
    older = _conversation(
        workspace_id,
        user_id,
        updated_at=datetime(2026, 5, 20, tzinfo=UTC),
    )
    newer = _conversation(
        workspace_id,
        user_id,
        updated_at=datetime(2026, 5, 21, tzinfo=UTC),
    )
    db = _make_db_for_route(
        conversations=[newer, older],
        messages={
            newer.id: [
                _message(
                    newer.id,
                    "user",
                    "Reach dormant ecommerce leads",
                    created_at=newer.created_at,
                ),
                _message(
                    newer.id,
                    "assistant",
                    "Done",
                    created_at=newer.created_at + timedelta(seconds=1),
                ),
            ],
            older.id: [_message(older.id, "user", "Older chat", created_at=older.created_at)],
        },
    )

    conversations = await crm_assistant.list_assistant_conversations(
        workspace_id=workspace_id,
        current_user=_user(user_id),
        db=db,
        workspace=_workspace(workspace_id),
    )
    await crm_assistant.delete_assistant_conversation(
        workspace_id=workspace_id,
        conversation_id=newer.id,
        current_user=_user(user_id),
        db=db,
        workspace=_workspace(workspace_id),
    )

    assert [conversation.id for conversation in conversations] == [str(newer.id), str(older.id)]
    assert conversations[0].title == "Reach dormant ecommerce leads"
    assert conversations[0].message_count == 2
    db.delete.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_stream_endpoint_emits_sse_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    app = _make_stream_app()

    async def get_current_user_override() -> User:
        return _user()

    async def get_workspace_override() -> Workspace:
        return _workspace(workspace_id)

    async def get_db_override() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    monkeypatch.setattr(crm_assistant, "stream_assistant_message", _noop_stream)
    from app.api.deps import get_current_user, get_db, get_workspace

    app.dependency_overrides[get_current_user] = get_current_user_override
    app.dependency_overrides[get_workspace] = get_workspace_override
    app.dependency_overrides[get_db] = get_db_override

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/assistant/chat/stream",
            json={"message": "Hi", "conversation_id": str(conversation_id)},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "delta", "text": "Hello"}' in response.text
    assert f'"conversation_id": "{conversation_id}"' in response.text
