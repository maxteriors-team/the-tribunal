"""Regression tests: workers must claim rows before acting on them.

Background workers all run in the single ``backend-api`` process today, so a
missing row claim is invisible. The moment a second replica exists, any worker
that reads a queue of ``pending`` rows without locking them will have both
replicas read the same rows before either writes the "done" state — and do the
work twice.

That is not a theoretical tidiness concern for the queries covered here:

* ``NudgeDeliveryService.deliver_pending_nudges`` sends operator SMS/email.
* ``EmailCampaignWorker`` sends the campaign email to a contact.
* ``TranscriptAnalysisWorker`` pays OpenAI per transcript.
* ``ReputationWorker`` advances number warming stages, where double-advancing
  ramps send volume faster than deliverability allows.

Each test compiles the statement the code actually emits and asserts the
``FOR UPDATE ... SKIP LOCKED`` claim is present. ``SKIP LOCKED`` (rather than a
plain ``FOR UPDATE``) matters too: it makes the second replica move on instead
of blocking on the first replica's transaction and holding a pooled connection
open while it waits.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.services.nudges.nudge_delivery import NudgeDeliveryService
from app.workers.email_campaign_worker import EmailCampaignWorker
from app.workers.reputation_worker import ReputationWorker
from app.workers.transcript_analysis_worker import TranscriptAnalysisWorker
from tests.factories import CampaignFactory


class _EmptyResult:
    """Result stub that yields no rows, so callers short-circuit immediately."""

    def scalars(self) -> _EmptyResult:
        return self

    def all(self) -> list[Any]:
        return []

    def scalar_one_or_none(self) -> None:
        return None


class _RecordingSession:
    """AsyncSession stand-in that captures every statement it is handed."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> _EmptyResult:
        self.statements.append(statement)
        return _EmptyResult()

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def add(self, _obj: Any) -> None:
        return None


def _compiled(statement: Any) -> str:
    """Render a statement as the PostgreSQL SQL the server would receive."""
    return str(statement.compile(dialect=postgresql.dialect())).upper()


def _assert_claims_rows(session: _RecordingSession, *, table: str) -> None:
    """Assert some captured SELECT claims ``table`` with SKIP LOCKED."""
    selects = [_compiled(s) for s in session.statements]
    claiming = [
        sql for sql in selects if "FOR UPDATE" in sql and table.upper() in sql
    ]
    assert claiming, (
        f"No statement claimed {table!r}. Without FOR UPDATE a second replica "
        f"reads the same rows and repeats the work. Captured SQL: {selects}"
    )
    for sql in claiming:
        assert "SKIP LOCKED" in sql, (
            f"{table!r} is locked with a plain FOR UPDATE. Use SKIP LOCKED so a "
            "second replica moves on instead of blocking on the lock and "
            f"holding a pooled connection while it waits. SQL: {sql}"
        )


@asynccontextmanager
async def _session_ctx(session: _RecordingSession) -> Any:
    yield session


async def test_pending_nudges_are_claimed_before_delivery() -> None:
    """Two replicas must not both deliver the same pending nudge."""
    session = _RecordingSession()

    await NudgeDeliveryService().deliver_pending_nudges(session, uuid.uuid4())  # type: ignore[arg-type]

    _assert_claims_rows(session, table="human_nudges")


async def test_email_campaign_enrollments_are_claimed_before_sending() -> None:
    """The email worker must claim enrollments like its SMS sibling does."""
    session = _RecordingSession()
    worker = EmailCampaignWorker()
    worker._check_completion = AsyncMock()  # type: ignore[method-assign]
    campaign = CampaignFactory.build(
        workspace_id=uuid.uuid4(),
        initial_message="Hello {first_name}",
        email_subject="A note",
    )

    await worker._process_campaign_contacts(campaign, session, worker.logger)  # type: ignore[arg-type]

    _assert_claims_rows(session, table="campaign_contacts")


async def test_transcript_batch_is_claimed_before_paying_openai() -> None:
    """Unanalyzed call outcomes must be claimed so OpenAI isn't billed twice."""
    session = _RecordingSession()

    with patch(
        "app.workers.transcript_analysis_worker.system_session",
        return_value=_session_ctx(session),
    ):
        await TranscriptAnalysisWorker()._process_batch()

    _assert_claims_rows(session, table="call_outcomes")


async def test_reputation_numbers_are_claimed_before_advancing_warming() -> None:
    """Warming advancement must not run twice against the same numbers."""
    session = _RecordingSession()

    with patch(
        "app.workers.reputation_worker.system_session",
        return_value=_session_ctx(session),
    ):
        await ReputationWorker()._process_items()

    _assert_claims_rows(session, table="phone_numbers")


@pytest.mark.parametrize(
    ("module_path", "symbol"),
    [
        ("app.workers.campaign_worker", "CampaignWorker"),
        ("app.workers.voice_campaign_worker", "VoiceCampaignWorker"),
    ],
)
def test_sibling_campaign_workers_still_claim(module_path: str, symbol: str) -> None:
    """The SMS/voice workers already claimed rows — keep it that way.

    These are the reference implementations the email worker was aligned to, so
    a regression here would quietly reintroduce duplicate sends on the channels
    that were previously safe.
    """
    import importlib
    import inspect

    module = importlib.import_module(module_path)
    source = inspect.getsource(getattr(module, symbol))

    assert "skip_locked=True" in source, (
        f"{symbol} no longer claims rows with SKIP LOCKED — duplicate outbound "
        "sends become possible as soon as a second replica runs."
    )
