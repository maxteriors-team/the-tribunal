"""Route and service regression tests for human-approved AI corrections."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership
from app.api.v1.conversations import router
from app.models.agent_training_example import AgentTrainingExample
from app.models.conversation import MessageDirection
from app.services.ai.teach_ai import SavedTrainingExample, save_training_example

WORKSPACE_ID = uuid.uuid4()
CONVERSATION_ID = uuid.uuid4()
SOURCE_MESSAGE_ID = uuid.uuid4()
AGENT_ID = uuid.uuid4()


def _result(value: object | None = None, *, row: tuple[object, ...] | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.one_or_none.return_value = row
    return result


def _conversation(*, workspace_id: uuid.UUID = WORKSPACE_ID) -> SimpleNamespace:
    return SimpleNamespace(id=CONVERSATION_ID, workspace_id=workspace_id, contact_id=101)


def _message(
    *,
    message_id: uuid.UUID,
    direction: MessageDirection,
    body: str,
    created_at: datetime,
    is_ai: bool = False,
    agent_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        conversation_id=CONVERSATION_ID,
        direction=direction,
        body=body,
        created_at=created_at,
        is_ai=is_ai,
        agent_id=agent_id,
    )


def _db(*results: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_save_training_example_creates_tenant_scoped_lesson_and_safe_audit() -> None:
    now = datetime.now(UTC)
    source = _message(
        message_id=SOURCE_MESSAGE_ID,
        direction=MessageDirection.OUTBOUND,
        body="We can help. Book now.",
        created_at=now,
        is_ai=True,
        agent_id=AGENT_ID,
    )
    inbound = _message(
        message_id=uuid.uuid4(),
        direction=MessageDirection.INBOUND,
        body="How much does gutter cleaning cost?",
        created_at=now - timedelta(minutes=1),
    )
    agent = SimpleNamespace(id=AGENT_ID, workspace_id=WORKSPACE_ID, name="Lead agent")
    db = _db(
        _result(_conversation()),
        _result(row=(source, agent)),
        _result(inbound),
        _result(None),
    )

    saved = await save_training_example(
        db,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        source_message_id=SOURCE_MESSAGE_ID,
        ideal_response="Happy to help—roughly how many stories is the home?",
        note="Ask one scope question first.",
        user_id=7,
    )

    assert saved.agent_name == "Lead agent"
    assert saved.example.workspace_id == WORKSPACE_ID
    assert saved.example.customer_message == inbound.body
    assert saved.example.ideal_response.startswith("Happy to help")
    audit = db.add.call_args_list[-1].args[0]
    assert set(audit.action_payload) == {
        "training_example_id",
        "conversation_id",
        "source_message_id",
        "operation",
    }
    assert inbound.body not in str(audit.action_payload)
    assert source.body not in str(audit.action_payload)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_training_example_hides_cross_workspace_conversation() -> None:
    db = _db(_result(None))

    with pytest.raises(Exception) as error:
        await save_training_example(
            db,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            source_message_id=SOURCE_MESSAGE_ID,
            ideal_response="A useful alternative",
            note=None,
            user_id=7,
        )

    assert getattr(error.value, "status_code", None) == 404
    assert db.add.call_count == 0


@pytest.mark.asyncio
async def test_save_training_example_rejects_non_ai_source_and_no_prior_inbound() -> None:
    db = _db(_result(_conversation()), _result(row=None))
    with pytest.raises(Exception) as error:
        await save_training_example(
            db,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            source_message_id=SOURCE_MESSAGE_ID,
            ideal_response="A useful alternative",
            note=None,
            user_id=7,
        )
    assert getattr(error.value, "status_code", None) == 422

    now = datetime.now(UTC)
    source = _message(
        message_id=SOURCE_MESSAGE_ID,
        direction=MessageDirection.OUTBOUND,
        body="Original answer",
        created_at=now,
        is_ai=True,
        agent_id=AGENT_ID,
    )
    agent = SimpleNamespace(id=AGENT_ID, workspace_id=WORKSPACE_ID, name="Agent")
    db = _db(_result(_conversation()), _result(row=(source, agent)), _result(None))
    with pytest.raises(Exception) as error:
        await save_training_example(
            db,
            workspace_id=WORKSPACE_ID,
            conversation_id=CONVERSATION_ID,
            source_message_id=SOURCE_MESSAGE_ID,
            ideal_response="A useful alternative",
            note=None,
            user_id=7,
        )
    assert getattr(error.value, "status_code", None) == 422


@pytest.mark.asyncio
async def test_save_training_example_upserts_existing_source() -> None:
    now = datetime.now(UTC)
    source = _message(
        message_id=SOURCE_MESSAGE_ID,
        direction=MessageDirection.OUTBOUND,
        body="Original answer",
        created_at=now,
        is_ai=True,
        agent_id=AGENT_ID,
    )
    inbound = _message(
        message_id=uuid.uuid4(),
        direction=MessageDirection.INBOUND,
        body="Customer asks",
        created_at=now - timedelta(seconds=5),
    )
    agent = SimpleNamespace(id=AGENT_ID, workspace_id=WORKSPACE_ID, name="Agent")
    existing = AgentTrainingExample(
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        conversation_id=CONVERSATION_ID,
        source_message_id=SOURCE_MESSAGE_ID,
        customer_message="Old question",
        ai_response="Old answer",
        ideal_response="Old correction",
    )
    db = _db(
        _result(_conversation()),
        _result(row=(source, agent)),
        _result(inbound),
        _result(existing),
    )

    saved = await save_training_example(
        db,
        workspace_id=WORKSPACE_ID,
        conversation_id=CONVERSATION_ID,
        source_message_id=SOURCE_MESSAGE_ID,
        ideal_response="New correction",
        note=None,
        user_id=9,
    )

    assert saved.example is existing
    assert existing.ideal_response == "New correction"
    assert existing.created_by_user_id == 9
    assert db.add.call_args_list[-1].args[0].action_payload["operation"] == "updated"


def _app(db: AsyncMock, *, role: str = "admin") -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/workspaces/{workspace_id}/conversations")

    async def override_db() -> AsyncIterator[AsyncMock]:
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7, is_active=True)
    app.dependency_overrides[get_membership] = lambda: SimpleNamespace(
        workspace_id=WORKSPACE_ID, role=role
    )
    return app


@pytest.mark.asyncio
async def test_teach_ai_route_requires_crm_write_and_serializes_saved_lesson() -> None:
    now = datetime.now(UTC)
    example = AgentTrainingExample(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        conversation_id=CONVERSATION_ID,
        source_message_id=SOURCE_MESSAGE_ID,
        created_by_user_id=7,
        customer_message="Private customer body",
        ai_response="Private AI body",
        ideal_response="Approved future reply",
        operator_note="Short note",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db = _db()
    app = _app(db)
    with patch(
        "app.api.v1.conversations.save_training_example",
        new=AsyncMock(return_value=SavedTrainingExample(example, "Lead agent")),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/workspaces/{WORKSPACE_ID}/conversations/{CONVERSATION_ID}/teach-ai",
                json={
                    "source_message_id": str(SOURCE_MESSAGE_ID),
                    "ideal_response": "Approved future reply",
                    "note": "Short note",
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_name"] == "Lead agent"
    assert payload["ideal_response"] == "Approved future reply"
    assert "customer_message" not in payload
    assert "ai_response" not in payload

    denied_app = _app(_db(), role="field")
    async with AsyncClient(
        transport=ASGITransport(app=denied_app), base_url="http://test"
    ) as client:
        denied = await client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/conversations/{CONVERSATION_ID}/teach-ai",
            json={
                "source_message_id": str(SOURCE_MESSAGE_ID),
                "ideal_response": "Approved future reply",
            },
        )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_teach_ai_route_rejects_empty_or_oversized_corrections() -> None:
    app = _app(_db())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        empty = await client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/conversations/{CONVERSATION_ID}/teach-ai",
            json={"source_message_id": str(SOURCE_MESSAGE_ID), "ideal_response": "   "},
        )
        oversized = await client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/conversations/{CONVERSATION_ID}/teach-ai",
            json={"source_message_id": str(SOURCE_MESSAGE_ID), "ideal_response": "x" * 1001},
        )

    assert empty.status_code == 422
    assert oversized.status_code == 422
