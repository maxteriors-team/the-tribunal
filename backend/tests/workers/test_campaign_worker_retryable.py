"""CampaignWorker — RetryableWorker contract.

Inherits retry behavior from ``BaseCampaignWorker``; this file pins down
the concrete subclass's configuration and DLQ routing on a synthetic failure.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.base_campaign_worker import BaseCampaignWorker
from app.workers.campaign_worker import CampaignWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(CampaignWorker, RetryableWorker)
    assert issubclass(CampaignWorker, BaseWorker)
    assert issubclass(CampaignWorker, BaseCampaignWorker)


def test_retry_configuration() -> None:
    assert CampaignWorker.COMPONENT_NAME == "campaign_worker"
    assert CampaignWorker.max_retries == 3
    assert CampaignWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_campaign_routes_to_dlq() -> None:
    worker = CampaignWorker()
    recorder = wire_worker_for_retry_test(worker)

    campaign = MagicMock(id=uuid4(), name="x")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("nope")

    item_key = f"campaign:{campaign.id}"
    await worker.execute_with_retry(fail, campaign, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "campaign_worker"
    assert recorder.calls[0]["item_key"] == item_key
