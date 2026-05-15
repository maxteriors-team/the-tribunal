"""VoiceCampaignWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

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
