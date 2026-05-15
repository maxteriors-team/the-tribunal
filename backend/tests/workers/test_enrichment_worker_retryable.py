"""EnrichmentWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.workers.base import BaseWorker
from app.workers.enrichment_worker import EnrichmentWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(EnrichmentWorker, RetryableWorker)
    assert issubclass(EnrichmentWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert EnrichmentWorker.COMPONENT_NAME == "enrichment_worker"
    assert EnrichmentWorker.max_retries == 3
    assert EnrichmentWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_contact_enrichment_routes_to_dlq() -> None:
    worker = EnrichmentWorker()
    recorder = wire_worker_for_retry_test(worker)

    contact = MagicMock(id=42)
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("scrape failed")

    item_key = f"contact:{contact.id}"
    await worker.execute_with_retry(fail, contact, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "enrichment_worker"
    assert recorder.calls[0]["item_key"] == item_key
