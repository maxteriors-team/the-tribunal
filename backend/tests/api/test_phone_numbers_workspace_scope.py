"""Tenant-isolation tests for the phone-number read routes.

The list/get handlers once skipped the ``workspace_id`` predicate on the claim
that phone numbers were "shared across workspaces" — they are not:
``phone_numbers.workspace_id`` is non-nullable and every write path already
scopes by it. These drive the handlers against a real DB (marked
``integration``; run with ``-m integration``) so the SQL predicate itself is
under test, which a mocked session would not cover.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import phone_numbers as phone_numbers_module
from app.api.v1.phone_numbers import (
    configure_inbound_calling,
    get_phone_number,
    list_phone_numbers,
    update_phone_number,
)
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.lead_source import LeadSource, LeadSourceCampaign, LeadSourceType
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace
from app.schemas.phone_number import (
    InboundCallConfigRequest,
    PhoneNumberResponse,
    PhoneNumberUpdate,
)
from app.services.telephony.inbound_call_readiness import InboundCallReadiness

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Phones Co", slug=f"pho-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _make_number(db: AsyncSession, workspace_id: uuid.UUID) -> PhoneNumber:
    number = PhoneNumber(
        workspace_id=workspace_id,
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(number)
    await db.flush()
    return number


# The handlers take ``current_user``/``membership`` purely as auth gates and
# never read them; the tenancy predicate is what these tests exercise.
_ANY = cast(Any, None)


async def test_list_returns_only_the_callers_workspace_numbers() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        mine = await _make_number(db, ws_a.id)
        theirs = await _make_number(db, ws_b.id)

        # page/page_size are passed explicitly: calling the handler directly
        # bypasses FastAPI's resolution of their ``Query(...)`` defaults.
        page = await list_phone_numbers(ws_a.id, _ANY, db, _ANY, page=1, page_size=100)

        returned = {item.id for item in page.items}
        assert mine.id in returned
        assert theirs.id not in returned


async def test_get_rejects_another_workspaces_number() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        theirs = await _make_number(db, ws_b.id)

        with pytest.raises(HTTPException) as exc:
            await get_phone_number(ws_a.id, theirs.id, _ANY, db, _ANY)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Phone number not found"


async def test_get_returns_an_owned_number() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        mine = await _make_number(db, ws.id)

        found = await get_phone_number(ws.id, mine.id, _ANY, db, _ANY)

        assert found.id == mine.id


async def test_deleting_lead_source_nulls_number_mapping_without_deleting_number() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        source = LeadSource(
            workspace_id=ws.id,
            name="Westside Truck Wrap",
            source_type=LeadSourceType.TRUCK_WRAP,
        )
        db.add(source)
        await db.flush()

        number = await _make_number(db, ws.id)
        number.lead_source_id = source.id
        await db.flush()
        number_id = number.id

        await db.delete(source)
        await db.flush()
        await db.refresh(number)

        assert number.id == number_id
        assert number.lead_source_id is None


async def test_update_sets_and_serializes_tracking_mapping() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        source = LeadSource(
            workspace_id=ws.id,
            name="Northside Yard Signs",
            source_type=LeadSourceType.YARD_SIGN,
        )
        db.add(source)
        await db.flush()
        campaign = LeadSourceCampaign(
            workspace_id=ws.id,
            lead_source_id=source.id,
            name="Spring Cleanup",
        )
        db.add(campaign)
        number = await _make_number(db, ws.id)
        await db.flush()

        updated = await update_phone_number(
            ws.id,
            number.id,
            PhoneNumberUpdate(
                lead_source_id=source.id,
                lead_source_campaign_id=campaign.id,
                tracking_label="  Northside route  ",
            ),
            _ANY,
            db,
            _ANY,
        )
        response = PhoneNumberResponse.model_validate(updated)

        assert response.lead_source_id == source.id
        assert response.lead_source_campaign_id == campaign.id
        assert response.tracking_label == "Northside route"
        assert response.lead_source is not None
        assert response.lead_source.name == "Northside Yard Signs"
        assert response.lead_source_campaign is not None
        assert response.lead_source_campaign.name == "Spring Cleanup"


async def test_agent_assignment_change_disables_ai_until_reactivated() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        agent = Agent(
            workspace_id=ws.id,
            name="Replacement Agent",
            system_prompt="Help inbound callers.",
            channel_mode="voice",
            voice_provider="openai",
            voice_id="alloy",
        )
        db.add(agent)
        phone = await _make_number(db, ws.id)
        phone.inbound_ai_enabled = True
        await db.commit()

        updated = await update_phone_number(
            ws.id,
            phone.id,
            PhoneNumberUpdate(assigned_agent_id=agent.id),
            _ANY,
            db,
            _ANY,
        )

        assert updated.assigned_agent_id == agent.id
        assert updated.inbound_ai_enabled is False


async def test_failed_provider_activation_leaves_database_kill_switch_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        agent = Agent(
            workspace_id=ws.id,
            name="Pilot Agent",
            system_prompt="Help inbound callers.",
            channel_mode="voice",
            voice_provider="openai",
            voice_id="alloy",
        )
        db.add(agent)
        phone = await _make_number(db, ws.id)
        phone.telnyx_phone_number_id = "provider-number-id"
        await db.commit()

        monkeypatch.setattr(
            phone_numbers_module,
            "evaluate_inbound_call_readiness",
            AsyncMock(return_value=InboundCallReadiness(checks=(), agent=agent)),
        )
        provider = MagicMock(
            configure_phone_number=AsyncMock(return_value=False),
            close=AsyncMock(),
        )
        monkeypatch.setattr(
            phone_numbers_module,
            "TelnyxSMSService",
            MagicMock(return_value=provider),
        )

        with pytest.raises(HTTPException) as exc:
            await configure_inbound_calling(
                ws.id,
                phone.id,
                InboundCallConfigRequest(
                    enabled=True,
                    assigned_agent_id=agent.id,
                    fallback_number="+12025550123",
                    transfer_destination_number="+12025550124",
                ),
                _ANY,
                db,
                _ANY,
            )

        assert exc.value.status_code == 502
        await db.refresh(phone)
        assert phone.inbound_ai_enabled is False


async def test_deactivation_commits_kill_switch_before_optional_config_validation() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        phone = await _make_number(db, ws.id)
        phone.inbound_ai_enabled = True
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await configure_inbound_calling(
                ws.id,
                phone.id,
                InboundCallConfigRequest(
                    enabled=False,
                    transfer_destination_number="+12025550124",
                ),
                _ANY,
                db,
                _ANY,
            )

        assert exc.value.status_code == 422
        await db.rollback()
        await db.refresh(phone)
        assert phone.inbound_ai_enabled is False
