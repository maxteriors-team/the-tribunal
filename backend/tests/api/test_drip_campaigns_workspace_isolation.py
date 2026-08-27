"""Workspace isolation regression tests for drip campaigns."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import Select

from app.api.v1 import drip_campaigns as drip_campaigns_module
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.drip_campaign import DripCampaign, DripCampaignStatus, DripEnrollment
from app.models.phone_number import PhoneNumber
from app.schemas.drip_campaign import DripCampaignCreate
from app.services.reactivation.drip_runner import enroll_contacts

WS_ID = uuid.uuid4()
CAMPAIGN_ID = uuid.uuid4()


def _result(value: object | None = None, values: list[object] | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    scalars = MagicMock()
    scalars.all.return_value = values if values is not None else ([] if value is None else [value])
    result.scalars.return_value = scalars
    return result


def _query_sql(query: object) -> str:
    assert isinstance(query, Select)
    return str(query.compile(compile_kwargs={"literal_binds": True})).lower()


def _assert_scoped_query(query: object, table_name: str) -> None:
    sql = _query_sql(query)
    assert table_name in sql
    assert "workspace_id" in sql
    assert WS_ID.hex in sql


def _agent(*, workspace_id: uuid.UUID = WS_ID) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Drip Agent",
        channel_mode="text",
        system_prompt="Be helpful",
        is_active=True,
    )


def _sender(
    *,
    workspace_id: uuid.UUID = WS_ID,
    is_active: bool = True,
    sms_enabled: bool = True,
) -> PhoneNumber:
    return PhoneNumber(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        phone_number="+15551234567",
        is_active=is_active,
        sms_enabled=sms_enabled,
        voice_enabled=True,
        imessage_enabled=False,
    )


def _campaign(*, agent_id: uuid.UUID | None = None) -> DripCampaign:
    now = datetime.now(UTC)
    return DripCampaign(
        id=CAMPAIGN_ID,
        workspace_id=WS_ID,
        agent_id=agent_id or uuid.uuid4(),
        name="Drip Campaign",
        status=DripCampaignStatus.DRAFT,
        from_phone_number="+15551234567",
        sequence_steps=[{"day": 0, "message": "Hi"}],
        timezone="America/New_York",
        messages_per_minute=10,
        total_enrolled=0,
        total_messages_sent=0,
        total_responded=0,
        total_appointments_booked=0,
        created_at=now,
        updated_at=now,
    )


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def refresh(campaign: DripCampaign) -> None:
        now = datetime.now(UTC)
        campaign.id = campaign.id or CAMPAIGN_ID
        campaign.total_enrolled = campaign.total_enrolled or 0
        campaign.total_messages_sent = campaign.total_messages_sent or 0
        campaign.total_responded = campaign.total_responded or 0
        campaign.total_appointments_booked = campaign.total_appointments_booked or 0
        campaign.total_completed = campaign.total_completed or 0
        campaign.total_cancelled = campaign.total_cancelled or 0
        campaign.created_at = campaign.created_at or now
        campaign.updated_at = campaign.updated_at or now

    db.refresh = AsyncMock(side_effect=refresh)
    return db


async def test_create_drip_campaign_hides_foreign_agent() -> None:
    db = _db()
    foreign_agent = _agent(workspace_id=uuid.uuid4())
    valid_sender = _sender()
    agent_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _query_sql(query)
        if "agents" in sql:
            agent_queries.append(query)
            return _result(None if "workspace_id" in sql else foreign_agent)
        if "phone_numbers" in sql:
            return _result(valid_sender)
        raise AssertionError(f"Unexpected query: {sql}")

    db.execute = AsyncMock(side_effect=execute)

    with pytest.raises(HTTPException) as exc_info:
        await drip_campaigns_module.create_drip_campaign(
            workspace_id=WS_ID,
            request=DripCampaignCreate(
                name="Drip Campaign",
                agent_id=foreign_agent.id,
                from_phone_number=valid_sender.phone_number,
                sequence_steps=[{"step": 0, "delay_days": 0, "message": "Hi", "type": "sms"}],
            ),
            current_user=MagicMock(),
            db=db,
            workspace=MagicMock(id=WS_ID),
        )

    assert exc_info.value.status_code in {400, 404}
    assert agent_queries
    _assert_scoped_query(agent_queries[0], "agents")
    db.add.assert_not_called()


@pytest.mark.parametrize(
    ("sender", "invalid_reason"),
    [
        (_sender(workspace_id=uuid.uuid4()), "foreign"),
        (_sender(is_active=False), "inactive"),
        (_sender(sms_enabled=False), "wrong-capability"),
    ],
    ids=["foreign", "inactive", "wrong-capability"],
)
async def test_create_drip_campaign_rejects_invalid_sender_number(
    sender: PhoneNumber,
    invalid_reason: str,
) -> None:
    db = _db()
    valid_agent = _agent()
    phone_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _query_sql(query)
        if "agents" in sql:
            return _result(valid_agent)
        if "phone_numbers" in sql:
            phone_queries.append(query)
            filtered_out = (
                (invalid_reason == "foreign" and "workspace_id" in sql)
                or (invalid_reason == "inactive" and "is_active" in sql)
                or (invalid_reason == "wrong-capability" and "sms_enabled" in sql)
            )
            return _result(None if filtered_out else sender)
        raise AssertionError(f"Unexpected query: {sql}")

    db.execute = AsyncMock(side_effect=execute)

    with pytest.raises(HTTPException) as exc_info:
        await drip_campaigns_module.create_drip_campaign(
            workspace_id=WS_ID,
            request=DripCampaignCreate(
                name="Drip Campaign",
                agent_id=valid_agent.id,
                from_phone_number=sender.phone_number,
                sequence_steps=[{"step": 0, "delay_days": 0, "message": "Hi", "type": "sms"}],
            ),
            current_user=MagicMock(),
            db=db,
            workspace=MagicMock(id=WS_ID),
        )

    assert exc_info.value.status_code == 400
    assert phone_queries
    _assert_scoped_query(phone_queries[0], "phone_numbers")
    db.add.assert_not_called()


async def test_enroll_contacts_ignores_foreign_workspace_contact() -> None:
    db = _db()
    campaign = _campaign()
    own_contact = Contact(
        id=1,
        workspace_id=WS_ID,
        first_name="Own",
        phone_number="+15550000001",
        phone_hash="own-contact",
        status="new",
    )
    contact_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _query_sql(query)
        if "contacts" in sql and "drip_enrollments" not in sql:
            contact_queries.append(query)
            if "contacts.id = 2" in sql:
                return _result(None)
            return _result(own_contact, [own_contact])
        if "drip_enrollments" in sql:
            return _result(None)
        raise AssertionError(f"Unexpected query: {sql}")

    db.execute = AsyncMock(side_effect=execute)

    enrolled = await enroll_contacts(campaign, [1, 2], db)

    assert enrolled == 1
    created = [call.args[0] for call in db.add.call_args_list]
    assert all(isinstance(item, DripEnrollment) for item in created)
    assert [item.contact_id for item in created] == [1]
    assert contact_queries
    _assert_scoped_query(contact_queries[0], "contacts")
