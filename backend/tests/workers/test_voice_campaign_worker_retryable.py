"""VoiceCampaignWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql import Select

from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.models.phone_number import PhoneNumber
from app.workers.base import BaseWorker
from app.workers.base_campaign_worker import BaseCampaignWorker
from app.workers.retryable import RetryableWorker
from app.workers.voice_campaign_worker import VoiceCampaignWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(VoiceCampaignWorker, RetryableWorker)
    assert issubclass(VoiceCampaignWorker, BaseWorker)
    assert issubclass(VoiceCampaignWorker, BaseCampaignWorker)


def test_retry_configuration() -> None:
    assert VoiceCampaignWorker.COMPONENT_NAME == "voice_campaign_worker"
    assert VoiceCampaignWorker.max_retries == 3
    assert VoiceCampaignWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_campaign_routes_to_dlq() -> None:
    worker = VoiceCampaignWorker()
    recorder = wire_worker_for_retry_test(worker)

    campaign = MagicMock(id=uuid4(), name="voice")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("voice campaign blew up")

    item_key = f"campaign:{campaign.id}"
    await worker.execute_with_retry(fail, campaign, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "voice_campaign_worker"
    assert recorder.calls[0]["item_key"] == item_key


def _sql(query: object) -> str:
    assert isinstance(query, Select)
    return str(query.compile(compile_kwargs={"literal_binds": True})).lower()


def _scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _pending_result(contact: CampaignContact) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = [contact]
    return result


def _invalid_sender(workspace_id: UUID, reason: str) -> PhoneNumber:
    return PhoneNumber(
        id=uuid4(),
        workspace_id=uuid4() if reason == "foreign" else workspace_id,
        phone_number="+15551234567",
        is_active=reason != "inactive",
        sms_enabled=True,
        voice_enabled=reason != "wrong-capability",
        imessage_enabled=False,
    )


@pytest.mark.parametrize("invalid_reason", ["foreign", "inactive", "wrong-capability"])
@pytest.mark.asyncio
async def test_invalid_runtime_sender_stops_before_voice_provider_call(
    invalid_reason: str,
) -> None:
    workspace_id = uuid4()
    campaign = Campaign(
        id=uuid4(),
        workspace_id=workspace_id,
        campaign_type=CampaignType.VOICE_SMS_FALLBACK,
        status=CampaignStatus.RUNNING,
        name="Voice Campaign",
        from_phone_number="+15551234567",
        voice_agent_id=uuid4(),
        voice_connection_id=None,
        enable_machine_detection=True,
        calls_per_minute=5,
        calls_attempted=0,
        error_count=0,
    )
    contact = Contact(
        id=1,
        workspace_id=workspace_id,
        first_name="Ava",
        phone_number="+15550000001",
        phone_hash="voice-contact",
        status="new",
    )
    campaign_contact = CampaignContact(
        id=uuid4(),
        campaign_id=campaign.id,
        contact_id=contact.id,
        status=CampaignContactStatus.PENDING,
        opted_out=False,
        priority=0,
        call_attempts=0,
    )
    campaign_contact.contact = contact
    sender = _invalid_sender(workspace_id, invalid_reason)
    phone_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _sql(query)
        if "phone_numbers" in sql:
            phone_queries.append(query)
            filtered_out = (
                (invalid_reason == "foreign" and "workspace_id" in sql)
                or (invalid_reason == "inactive" and "is_active" in sql)
                or (invalid_reason == "wrong-capability" and "voice_enabled" in sql)
            )
            return _scalar_result(None if filtered_out else sender)
        if "campaign_contacts" in sql:
            return _pending_result(campaign_contact)
        raise AssertionError(f"Unexpected query: {sql}")

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()
    voice_service = MagicMock()
    voice_service.initiate_call = AsyncMock(return_value=MagicMock(id=uuid4()))
    voice_service.close = AsyncMock()
    worker = VoiceCampaignWorker()

    with (
        patch(
            "app.workers.voice_campaign_worker.TelnyxVoiceService",
            return_value=voice_service,
        ),
        patch.object(worker, "_cleanup_stuck_calls", new=AsyncMock()),
        patch.object(worker, "_check_completion", new=AsyncMock()),
    ):
        await worker._process_campaign_contacts(campaign, db, MagicMock())

    voice_service.initiate_call.assert_not_awaited()
    assert campaign.status == CampaignStatus.PAUSED
    assert phone_queries
    sql = _sql(phone_queries[0])
    assert "phone_numbers.workspace_id" in sql
    assert workspace_id.hex in sql
