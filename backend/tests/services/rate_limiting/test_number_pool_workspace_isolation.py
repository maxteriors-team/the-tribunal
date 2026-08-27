"""Tenant-isolation regressions for campaign sender number selection."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.sql import Select

from app.models.campaign import Campaign, CampaignType
from app.models.campaign_number_pool import CampaignNumberPool
from app.models.phone_number import PhoneNumber, PhoneNumberHealthStatus
from app.services.rate_limiting.number_pool import NumberPoolManager

WS_ID = uuid.uuid4()


def _foreign_sender() -> PhoneNumber:
    return PhoneNumber(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        phone_number="+15551234567",
        is_active=True,
        sms_enabled=True,
        voice_enabled=True,
        imessage_enabled=False,
        health_status=PhoneNumberHealthStatus.HEALTHY,
        daily_limit=75,
        hourly_limit=10,
        messages_sent_7d=0,
        warming_stage=0,
    )


def _campaign(*, use_number_pool: bool = False) -> Campaign:
    return Campaign(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        campaign_type=CampaignType.SMS,
        name="Campaign",
        from_phone_number=None if use_number_pool else "+15551234567",
        use_number_pool=use_number_pool,
    )


def _sql(query: object) -> str:
    assert isinstance(query, Select)
    return str(query.compile(compile_kwargs={"literal_binds": True})).lower()


async def test_legacy_campaign_sender_cannot_resolve_foreign_workspace_number() -> None:
    db = AsyncMock()
    foreign_sender = _foreign_sender()
    sender_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _sql(query)
        if "phone_numbers" not in sql:
            raise AssertionError(f"Unexpected query: {sql}")
        sender_queries.append(query)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None if "workspace_id" in sql else foreign_sender
        return result

    db.execute = AsyncMock(side_effect=execute)
    manager = NumberPoolManager()

    with patch.object(manager, "_phone_has_capacity", new=AsyncMock(return_value=True)):
        selected = await manager.get_next_available_number(
            _campaign(), db, consume_rate_limit=False
        )

    assert selected is None
    assert sender_queries
    sql = _sql(sender_queries[0])
    assert "phone_numbers.workspace_id" in sql
    assert WS_ID.hex in sql


async def test_number_pool_cannot_select_foreign_workspace_number() -> None:
    db = AsyncMock()
    foreign_sender = _foreign_sender()
    campaign = _campaign(use_number_pool=True)
    pool_entry = CampaignNumberPool(
        campaign_id=campaign.id,
        phone_number_id=foreign_sender.id,
        is_active=True,
        priority=0,
    )
    pool_entry.phone_number = foreign_sender
    sender_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _sql(query)
        if "campaign_number_pools" not in sql:
            raise AssertionError(f"Unexpected query: {sql}")
        sender_queries.append(query)
        result = MagicMock()
        result.scalars.return_value.all.return_value = (
            [] if "phone_numbers.workspace_id" in sql else [pool_entry]
        )
        return result

    db.execute = AsyncMock(side_effect=execute)
    manager = NumberPoolManager()

    with patch.object(manager, "_phone_has_capacity", new=AsyncMock(return_value=True)):
        selected = await manager.get_next_available_number(campaign, db, consume_rate_limit=False)

    assert selected is None
    assert sender_queries
    sql = _sql(sender_queries[0])
    assert "phone_numbers.workspace_id" in sql
    assert WS_ID.hex in sql
