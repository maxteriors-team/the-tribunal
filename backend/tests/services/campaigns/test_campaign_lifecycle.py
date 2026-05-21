"""Tests for shared campaign lifecycle transitions."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.campaign import CampaignStatus
from app.services.campaigns.campaign_lifecycle import (
    CampaignLifecycleError,
    pause_campaign,
    resume_campaign,
    start_campaign,
    summarize_campaign,
)


def _make_campaign(status: CampaignStatus = CampaignStatus.DRAFT) -> MagicMock:
    campaign = MagicMock()
    campaign.id = uuid.uuid4()
    campaign.name = "Spring Promo"
    campaign.status = status
    campaign.campaign_type = "sms"
    campaign.total_contacts = 10
    campaign.messages_sent = 5
    campaign.messages_delivered = 4
    campaign.messages_failed = 1
    campaign.replies_received = 2
    campaign.contacts_qualified = 1
    campaign.contacts_opted_out = 1
    campaign.appointments_booked = 1
    campaign.appointments_completed = 0
    campaign.calls_attempted = 0
    campaign.calls_answered = 0
    campaign.sms_fallbacks_sent = 0
    campaign.guarantee_target = None
    campaign.guarantee_status = None
    campaign.started_at = None
    campaign.completed_at = None
    return campaign


@pytest.mark.asyncio
async def test_start_campaign_sets_running_status() -> None:
    campaign = _make_campaign(CampaignStatus.DRAFT)

    result = await start_campaign(AsyncMock(), campaign, contact_count=3)

    assert result.status == CampaignStatus.RUNNING
    assert result.contact_count == 3
    assert campaign.status == CampaignStatus.RUNNING
    assert campaign.started_at is not None


@pytest.mark.asyncio
async def test_start_campaign_rejects_invalid_transition() -> None:
    campaign = _make_campaign(CampaignStatus.COMPLETED)

    with pytest.raises(CampaignLifecycleError, match="Cannot start"):
        await start_campaign(AsyncMock(), campaign, contact_count=3)


@pytest.mark.asyncio
async def test_start_campaign_rejects_no_contacts() -> None:
    campaign = _make_campaign(CampaignStatus.DRAFT)

    with pytest.raises(CampaignLifecycleError, match="no contacts"):
        await start_campaign(AsyncMock(), campaign, contact_count=0)


@pytest.mark.asyncio
async def test_pause_campaign_sets_paused_status() -> None:
    campaign = _make_campaign(CampaignStatus.RUNNING)

    result = await pause_campaign(campaign)

    assert result.status == CampaignStatus.PAUSED
    assert campaign.status == CampaignStatus.PAUSED


@pytest.mark.asyncio
async def test_pause_campaign_rejects_non_running_campaign() -> None:
    campaign = _make_campaign(CampaignStatus.DRAFT)

    with pytest.raises(CampaignLifecycleError, match="running"):
        await pause_campaign(campaign)


@pytest.mark.asyncio
async def test_resume_campaign_sets_running_status() -> None:
    campaign = _make_campaign(CampaignStatus.PAUSED)

    result = await resume_campaign(AsyncMock(), campaign, contact_count=2)

    assert result.status == CampaignStatus.RUNNING
    assert result.contact_count == 2
    assert campaign.status == CampaignStatus.RUNNING


@pytest.mark.asyncio
async def test_resume_campaign_rejects_no_contacts() -> None:
    campaign = _make_campaign(CampaignStatus.PAUSED)

    with pytest.raises(CampaignLifecycleError, match="no contacts"):
        await resume_campaign(AsyncMock(), campaign, contact_count=0)


def test_summarize_campaign_returns_rates() -> None:
    campaign = _make_campaign(CampaignStatus.RUNNING)

    summary = summarize_campaign(campaign)

    assert summary["id"] == str(campaign.id)
    assert summary["status"] == "running"
    assert summary["rates"] == {
        "reply_rate": 0.4,
        "delivery_rate": 0.8,
        "qualification_rate": 0.1,
    }
