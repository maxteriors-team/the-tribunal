"""Workspace isolation tests for voice campaign FK validation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql import Select

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import voice_campaigns as voice_campaigns_module
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignStatus, CampaignType
from app.models.contact import Contact

WS_ID = uuid.uuid4()
CAMPAIGN_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_all_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


def _rows_result(rows: list[tuple[object, ...]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _assert_scoped_query(query: object, table_name: str) -> None:
    assert isinstance(query, Select)
    compiled = str(query.compile(compile_kwargs={"literal_binds": True})).lower()
    assert table_name in compiled
    assert "workspace_id" in compiled
    assert WS_ID.hex in compiled


def _make_workspace() -> MagicMock:
    workspace = MagicMock()
    workspace.id = WS_ID
    workspace.is_active = True
    return workspace


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.is_active = True
    return user


def _make_agent(
    *,
    agent_id: uuid.UUID | None = None,
    channel_mode: str = "both",
    workspace_id: uuid.UUID = WS_ID,
) -> Agent:
    return Agent(
        id=agent_id or uuid.uuid4(),
        workspace_id=workspace_id,
        name="Voice Agent",
        description="Handles calls",
        channel_mode=channel_mode,
        system_prompt="Be helpful",
        is_active=True,
    )


def _make_campaign(*, campaign_id: uuid.UUID = CAMPAIGN_ID) -> Campaign:
    now = datetime.now(UTC)
    return Campaign(
        id=campaign_id,
        workspace_id=WS_ID,
        campaign_type=CampaignType.VOICE_SMS_FALLBACK,
        status=CampaignStatus.DRAFT,
        name="Voice Campaign",
        description="Call homeowners",
        from_phone_number="+15551234567",
        voice_agent_id=uuid.uuid4(),
        sms_fallback_agent_id=None,
        agent_id=None,
        initial_message=None,
        ai_enabled=True,
        timezone="America/New_York",
        total_contacts=0,
        calls_attempted=0,
        calls_answered=0,
        calls_no_answer=0,
        calls_busy=0,
        calls_voicemail=0,
        sms_fallbacks_sent=0,
        messages_sent=0,
        messages_delivered=0,
        messages_failed=0,
        replies_received=0,
        contacts_qualified=0,
        contacts_opted_out=0,
        appointments_booked=0,
        appointments_completed=0,
        created_at=now,
        updated_at=now,
    )


def _make_contact(contact_id: int) -> Contact:
    return Contact(
        id=contact_id,
        workspace_id=WS_ID,
        first_name="Ava",
        phone_number=f"+1555000{contact_id:04d}",
        phone_hash=f"phone-{contact_id}",
        status="new",
    )


def _make_auth_test_app(mock_db: AsyncMock) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return _make_workspace()

    async def override_get_current_user() -> MagicMock:
        return _make_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.include_router(
        voice_campaigns_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/voice-campaigns",
    )
    return app


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
async def client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    app = _make_auth_test_app(mock_db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


async def test_create_voice_campaign_hides_cross_workspace_voice_agent(
    client: AsyncClient,
    mock_db: AsyncMock,
) -> None:
    agent_id = uuid.uuid4()
    mock_db.execute = AsyncMock(return_value=_scalar_result(None))

    response = await client.post(
        f"/api/v1/workspaces/{WS_ID}/voice-campaigns",
        json={
            "name": "Voice Campaign",
            "from_phone_number": "+15551234567",
            "voice_agent_id": str(agent_id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Voice agent not found"
    _assert_scoped_query(mock_db.execute.await_args.args[0], "agents")


async def test_create_voice_campaign_hides_cross_workspace_sms_fallback_agent(
    client: AsyncClient,
    mock_db: AsyncMock,
) -> None:
    voice_agent = _make_agent(channel_mode="voice")
    sms_agent_id = uuid.uuid4()
    mock_db.execute = AsyncMock(
        side_effect=[
            _scalar_result(voice_agent),
            _scalar_result(None),
        ]
    )

    response = await client.post(
        f"/api/v1/workspaces/{WS_ID}/voice-campaigns",
        json={
            "name": "Voice Campaign",
            "from_phone_number": "+15551234567",
            "voice_agent_id": str(voice_agent.id),
            "sms_fallback_agent_id": str(sms_agent_id),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "SMS fallback agent not found"
    _assert_scoped_query(mock_db.execute.await_args_list[0].args[0], "agents")
    _assert_scoped_query(mock_db.execute.await_args_list[1].args[0], "agents")


async def test_add_contacts_to_voice_campaign_enrolls_only_workspace_contacts(
    client: AsyncClient,
    mock_db: AsyncMock,
) -> None:
    campaign = _make_campaign()
    contact = _make_contact(1)
    mock_db.execute = AsyncMock(
        side_effect=[
            _scalar_result(campaign),
            _scalars_all_result([contact]),
            _rows_result([]),
        ]
    )

    response = await client.post(
        f"/api/v1/workspaces/{WS_ID}/voice-campaigns/{CAMPAIGN_ID}/contacts",
        json={"contact_ids": [1, 2]},
    )

    assert response.status_code == 200
    assert response.json() == {"added": 1}
    _assert_scoped_query(mock_db.execute.await_args_list[0].args[0], "campaigns")
    _assert_scoped_query(mock_db.execute.await_args_list[1].args[0], "contacts")
    created_link = mock_db.add.call_args.args[0]
    assert created_link.contact_id == 1
    assert campaign.total_contacts == 1
