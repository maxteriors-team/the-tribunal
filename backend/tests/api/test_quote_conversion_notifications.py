"""Post-commit quote conversion notifications remain phase-specific."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.quotes import _aggregate_crew_notifications, _notify_job_assignment
from app.schemas.quote import CrewNotificationResult
from app.services.jobs import JobService


@pytest.mark.asyncio
async def test_takedown_notification_reports_partial_delivery_for_its_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async def recipients(*args: object, **kwargs: object) -> tuple[int, int]:
        return (11, 12)

    async def missing_key(*args: object, **kwargs: object) -> bool:
        return False

    async def notify(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            delivered_recipient_ids=(11,),
            delivered_recipient_count=1,
            failed_recipient_count=1,
        )

    async def remember_key(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(JobService, "assignment_recipient_user_ids", recipients)
    monkeypatch.setattr("app.api.v1.quotes.redis_idempotency_key_exists", missing_key)
    monkeypatch.setattr("app.api.v1.quotes.notify_workspace_event", notify)
    monkeypatch.setattr("app.api.v1.quotes.set_redis_idempotency_key", remember_key)
    start = datetime(2027, 1, 8, 14, tzinfo=UTC)

    result = await _notify_job_assignment(
        MagicMock(spec=AsyncSession),
        workspace_id=workspace_id,
        job_id=job_id,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=2),
        crew_id=None,
        technician_ids=(),
        phase="takedown",
    )

    assert result.status == "partial"
    assert result.recipient_count == 2
    assert result.sent_count == 1
    assert result.failed_count == 1
    assert captured["data"]["phase"] == "takedown"
    assert captured["title"] == "Christmas lighting takedown assigned"


def test_notification_aggregate_preserves_partial_phase_failure() -> None:
    result = _aggregate_crew_notifications(
        CrewNotificationResult(status="sent", recipient_count=2, sent_count=2),
        CrewNotificationResult(status="failed", recipient_count=1, failed_count=1),
    )

    assert result == CrewNotificationResult(
        status="partial",
        recipient_count=3,
        sent_count=2,
        failed_count=1,
    )
