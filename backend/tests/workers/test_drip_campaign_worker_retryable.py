"""DripCampaignWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
            "app.workers.drip_campaign_worker.AsyncSessionLocal",
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
