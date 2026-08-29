"""DripCampaignWorker — RetryableWorker contract."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql import Select

from app.models.contact import Contact
from app.models.drip_campaign import (
    DripCampaign,
    DripCampaignStatus,
    DripEnrollment,
    DripEnrollmentStatus,
)
from app.models.phone_number import PhoneNumber
from app.services.reactivation import drip_runner
from app.workers.base import BaseWorker
from app.workers.drip_campaign_worker import DripCampaignWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(DripCampaignWorker, RetryableWorker)
    assert issubclass(DripCampaignWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert DripCampaignWorker.COMPONENT_NAME == "drip_campaign_worker"
    assert DripCampaignWorker.max_retries == 3
    assert DripCampaignWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_drip_cycle_routes_to_dlq() -> None:
    worker = DripCampaignWorker()
    recorder = wire_worker_for_retry_test(worker)

    db_ctx = MagicMock()
    db_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    db_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "app.workers.drip_campaign_worker.system_session",
            MagicMock(return_value=db_ctx),
        ),
        patch(
            "app.workers.drip_campaign_worker.process_active_drip_campaigns",
            AsyncMock(side_effect=RuntimeError("drip blew up")),
        ),
    ):
        await worker._process_items()

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "drip_campaign_worker"
    assert recorder.calls[0]["item_key"] == "drip_campaigns_cycle"


def _sql(query: object) -> str:
    assert isinstance(query, Select)
    return str(query.compile(compile_kwargs={"literal_binds": True})).lower()


def _scalar_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _invalid_sender(workspace_id: UUID, reason: str) -> PhoneNumber:
    return PhoneNumber(
        id=uuid4(),
        workspace_id=uuid4() if reason == "foreign" else workspace_id,
        phone_number="+15551234567",
        is_active=reason != "inactive",
        sms_enabled=reason != "wrong-capability",
        voice_enabled=True,
        imessage_enabled=False,
    )


@pytest.mark.parametrize("invalid_reason", ["foreign", "inactive", "wrong-capability"])
@pytest.mark.asyncio
async def test_invalid_runtime_sender_stops_before_telnyx_call(
    invalid_reason: str,
) -> None:
    workspace_id = uuid4()
    campaign = DripCampaign(
        id=uuid4(),
        workspace_id=workspace_id,
        agent_id=uuid4(),
        name="Drip Campaign",
        status=DripCampaignStatus.ACTIVE,
        from_phone_number="+15551234567",
        sequence_steps=[{"step": 0, "message": "Hi {first_name}"}],
        sending_hours_start=None,
        sending_hours_end=None,
        timezone="America/New_York",
        total_messages_sent=0,
        total_cancelled=0,
        total_completed=0,
    )
    contact = Contact(
        id=1,
        workspace_id=workspace_id,
        first_name="Ava",
        last_name="Homeowner",
        phone_number="+15550000001",
        phone_hash="drip-contact",
        status="new",
    )
    enrollment = DripEnrollment(
        id=uuid4(),
        drip_campaign_id=campaign.id,
        contact_id=contact.id,
        status=DripEnrollmentStatus.ACTIVE,
        current_step=0,
        next_step_at=datetime.now(UTC),
        messages_sent=0,
    )
    enrollment.contact = contact
    sender = _invalid_sender(workspace_id, invalid_reason)
    phone_queries: list[object] = []

    async def execute(query: object) -> MagicMock:
        sql = _sql(query)
        if "phone_numbers" in sql:
            phone_queries.append(query)
            filtered_out = (
                (invalid_reason == "foreign" and "workspace_id" in sql)
                or (invalid_reason == "inactive" and "is_active" in sql)
                or (invalid_reason == "wrong-capability" and "sms_enabled" in sql)
            )
            return _scalar_result(None if filtered_out else sender)
        if "drip_enrollments" in sql:
            result = MagicMock()
            result.scalars.return_value.all.return_value = [enrollment]
            return result
        raise AssertionError(f"Unexpected query: {sql}")

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute)
    db.commit = AsyncMock()
    sms_service = MagicMock()
    sms_service.send_message = AsyncMock(return_value=MagicMock(id=uuid4(), conversation_id=None))
    sms_service.close = AsyncMock()

    with (
        patch.object(drip_runner.settings, "telnyx_api_key", "test-key"),
        patch.object(drip_runner, "TelnyxSMSService", MagicMock(return_value=sms_service)),
        patch.object(
            drip_runner.OptOutManager,
            "check_opt_out",
            new=AsyncMock(return_value=False),
        ),
        patch.object(
            drip_runner,
            "_resolve_from_number",
            new=AsyncMock(return_value=campaign.from_phone_number),
        ),
    ):
        await drip_runner._process_campaign(campaign, db)

    sms_service.send_message.assert_not_awaited()
    assert campaign.status == DripCampaignStatus.PAUSED
    assert phone_queries
    sql = _sql(phone_queries[0])
    assert "phone_numbers.workspace_id" in sql
    assert workspace_id.hex in sql
