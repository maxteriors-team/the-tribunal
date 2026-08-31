"""PostgreSQL coverage for declining a shared estimate.

Without a decline the estimate link is a dead end -- the client can read a price
but cannot answer it. These assert the answer is recorded once, survives a
repeat, and shows up on the page the client reloads.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.services.exceptions import NotFoundError
from app.db.session import AsyncSessionLocal, engine
from app.models.roofline_comparison import RooflineComparison
from app.models.workspace import Workspace
from app.services.quotes.quote_service import QuoteService

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def workspace_id() -> AsyncIterator[uuid.UUID]:
    value = uuid.uuid4()
    yield value
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Workspace).where(Workspace.id == value))
        await db.commit()


async def _shared_estimate(db, workspace_id: uuid.UUID) -> RooflineComparison:
    db.add(
        Workspace(
            id=workspace_id,
            name="Decline",
            slug=f"decline-{uuid.uuid4().hex[:8]}",
            settings={"timezone": "America/New_York"},
        )
    )
    await db.flush()
    comparison = RooflineComparison(
        workspace_id=workspace_id,
        feet=100,
        channels=0,
        proposal_side="permanent",
    )
    db.add(comparison)
    await db.commit()
    return comparison


async def test_client_decline_is_recorded_with_their_reason(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        comparison = await _shared_estimate(db, workspace_id)
        svc = QuoteService(db)

        result = await svc.decline_public_comparison(
            comparison.public_token, reason="Going with another company"
        )

        await db.refresh(comparison)
        assert result.is_declined is True
        assert comparison.declined_at is not None
        assert comparison.decline_reason == "Going with another company"


async def test_second_decline_keeps_when_interest_actually_died(workspace_id) -> None:
    """A double-tap or a reopened link must not move the timestamp forward."""
    async with AsyncSessionLocal() as db:
        comparison = await _shared_estimate(db, workspace_id)
        svc = QuoteService(db)

        await svc.decline_public_comparison(comparison.public_token, reason="Too expensive")
        await db.refresh(comparison)
        first_at = comparison.declined_at

        # Backdate nothing; just decline again with a different reason.
        result = await svc.decline_public_comparison(comparison.public_token, reason="Changed mind")

        await db.refresh(comparison)
        assert result.is_declined is True
        assert comparison.declined_at == first_at
        assert comparison.decline_reason == "Too expensive"


async def test_declined_estimate_reports_itself_declined_to_the_client_page(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        comparison = await _shared_estimate(db, workspace_id)
        svc = QuoteService(db)

        before = await svc.get_public_comparison(comparison.public_token)
        await svc.decline_public_comparison(comparison.public_token, reason=None)
        after = await svc.get_public_comparison(comparison.public_token)

        # The page has to stop asking for a decision it already has.
        assert before.is_declined is False
        assert after.is_declined is True


async def test_a_long_reason_is_trimmed_rather_than_failing_the_decline(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        comparison = await _shared_estimate(db, workspace_id)
        svc = QuoteService(db)

        await svc.decline_public_comparison(comparison.public_token, reason="x" * 4000)

        await db.refresh(comparison)
        # Losing the tail of their note beats rejecting their "no".
        assert comparison.decline_reason is not None
        assert len(comparison.decline_reason) == 1000
        assert comparison.declined_at is not None


async def test_unknown_token_is_not_found(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        await _shared_estimate(db, workspace_id)
        svc = QuoteService(db)

        with pytest.raises(NotFoundError):
            await svc.decline_public_comparison("not-a-real-token", reason=None)


async def test_blank_reason_is_stored_as_no_reason(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        comparison = await _shared_estimate(db, workspace_id)
        svc = QuoteService(db)

        await svc.decline_public_comparison(comparison.public_token, reason="   ")

        await db.refresh(comparison)
        # Whitespace is not feedback; the rep should see "no reason given".
        assert comparison.decline_reason is None
        assert comparison.declined_at is not None


async def test_decline_does_not_disturb_the_estimate_timestamps(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        comparison = await _shared_estimate(db, workspace_id)
        created = comparison.created_at
        svc = QuoteService(db)

        await svc.decline_public_comparison(comparison.public_token, reason=None)

        await db.refresh(comparison)
        assert comparison.created_at == created
        assert comparison.declined_at is not None
        assert comparison.declined_at >= created - timedelta(seconds=1)
        assert comparison.declined_at <= datetime.now(UTC) + timedelta(seconds=1)
