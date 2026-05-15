"""BaseCampaignWorker — RetryableWorker contract.

``BaseCampaignWorker`` is abstract; we instantiate a minimal concrete
subclass to exercise the mixin behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import QueryableAttribute

from app.models.campaign import CampaignType
from app.workers.base import BaseWorker
from app.workers.base_campaign_worker import BaseCampaignWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


class _StubCampaignWorker(BaseCampaignWorker):
    COMPONENT_NAME = "stub_campaign_worker"

    @property
    def campaign_type(self) -> CampaignType:
        return CampaignType.SMS

    @property
    def eager_loads(self) -> list[QueryableAttribute[Any]]:
        return []

    async def _process_campaign_contacts(self, campaign, db, log) -> None:  # type: ignore[no-untyped-def]
        return None

    def _get_remaining_filter(self, campaign):  # type: ignore[no-untyped-def]
        return None


def test_base_class_inherits_retryable_and_base() -> None:
    assert issubclass(BaseCampaignWorker, RetryableWorker)
    assert issubclass(BaseCampaignWorker, BaseWorker)


def test_retry_configuration_inherited_defaults() -> None:
    assert BaseCampaignWorker.max_retries == 3
    assert BaseCampaignWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_campaign_processing_routes_to_dlq() -> None:
    worker = _StubCampaignWorker()
    recorder = wire_worker_for_retry_test(worker)

    campaign = MagicMock(id=uuid4(), name="bad campaign")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("campaign blew up")

    item_key = f"campaign:{campaign.id}"
    await worker.execute_with_retry(fail, campaign, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "stub_campaign_worker"
    assert recorder.calls[0]["item_key"] == item_key
