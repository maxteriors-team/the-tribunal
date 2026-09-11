"""Entity-scoped branch conditions — the questions a contact-shaped run cannot ask.

``unsold_quote_worker`` exists as 798 lines of hand-written Python because the
workflow engine could not express it. The blocker was never the ladder or the
timing; it was that a ``branch`` step could only ask about the contact, while
every suppression rule in that worker asks about **a specific quote**.

These tests pin the three conditions that were previously impossible, plus the
multi-quote case that is the reason contact-scoping was wrong in the first
place. Each one is written as the ``filter_rules`` a workflow definition would
actually store in JSONB, not as a Python predicate, because the rules are the
thing being proven.

What is still not expressible here is recorded at the bottom of this file, so
the gap stays visible rather than being quietly rounded up to "done".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.services.automations.branching import (
    SUBJECT_CONTACT,
    contact_matches_rules,
    subject_matches_rules,
)
from app.workers.unsold_quote_worker import (
    POST_ESTIMATE_WINDOW_DAYS,
    REVIVABLE_STATUSES,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Each test owns its own connections; a pooled one belongs to a dead loop."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Revival",
        slug=f"revival-{uuid.uuid4().hex[:8]}",
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1313555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Dana",
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _quote(
    db,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    status: str = "sent",
    total: float = 4000.0,
    sent_at: datetime | None = None,
) -> Quote:
    quote = Quote(
        workspace_id=workspace_id,
        contact_id=contact_id,
        number=f"Q-{uuid.uuid4().hex[:8]}",
        status=status,
        total=total,
        subtotal=total,
        sent_at=sent_at if sent_at is not None else datetime.now(UTC) - timedelta(days=30),
    )
    db.add(quote)
    await db.flush()
    return quote


# --- The three conditions the old engine could not ask ------------------------


async def test_a_branch_can_ask_whether_this_quote_is_still_unsold() -> None:
    """Stop reason 1: the quote settled while the ladder was waiting.

    This is the question the whole sequence exists to answer, and the one a
    contact-shaped branch physically could not reach.
    """
    rules = [{"field": "status", "operator": "in", "value": list(REVIVABLE_STATUSES)}]

    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        still_open = await _quote(db, workspace_id=ws.id, contact_id=contact.id, status="sent")
        approved = await _quote(db, workspace_id=ws.id, contact_id=contact.id, status="approved")
        declined = await _quote(db, workspace_id=ws.id, contact_id=contact.id, status="declined")

        assert await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(still_open.id),
            rules=rules,
            subject_type="quote",
        )
        # A quote the customer already accepted must not be revived. Before
        # entity scoping this is the send that reached someone who had signed.
        assert not await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(approved.id),
            rules=rules,
            subject_type="quote",
        )
        assert not await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(declined.id),
            rules=rules,
            subject_type="quote",
        )

        await db.rollback()


async def test_a_branch_can_defer_to_the_post_estimate_window() -> None:
    """Stop reason 3: another sequence still owns this quote.

    Mutual exclusion between two cadences, expressed as a date predicate on the
    triggering record rather than as cross-worker Python.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=POST_ESTIMATE_WINDOW_DAYS)
    rules = [{"field": "sent_at", "operator": "lte", "value": cutoff.isoformat()}]

    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        fresh = await _quote(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            sent_at=now - timedelta(days=3),
        )
        matured = await _quote(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            sent_at=now - timedelta(days=40),
        )

        # Sent three days ago: the first-14-days cadence is still running it.
        assert not await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(fresh.id),
            rules=rules,
            subject_type="quote",
        )
        assert await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(matured.id),
            rules=rules,
            subject_type="quote",
        )

        await db.rollback()


async def test_a_branch_can_select_copy_by_quote_value() -> None:
    """High-value vs routine template selection, without duplicating send steps."""
    rules = [{"field": "total", "operator": "gte", "value": 8000}]

    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        routine = await _quote(db, workspace_id=ws.id, contact_id=contact.id, total=4000.0)
        high_value = await _quote(db, workspace_id=ws.id, contact_id=contact.id, total=12000.0)

        assert not await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(routine.id),
            rules=rules,
            subject_type="quote",
        )
        assert await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(high_value.id),
            rules=rules,
            subject_type="quote",
        )

        await db.rollback()


# --- Why contact scoping was the wrong shape ----------------------------------


async def test_one_contact_with_three_quotes_gets_three_answers() -> None:
    """The case that makes contact-scoped branching incorrect rather than limited.

    One contact, three quotes, three different states. A contact-shaped branch
    has one answer to give and would apply it to all three.
    """
    rules = [{"field": "status", "operator": "in", "value": list(REVIVABLE_STATUSES)}]

    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        sent = await _quote(db, workspace_id=ws.id, contact_id=contact.id, status="sent")
        approved = await _quote(db, workspace_id=ws.id, contact_id=contact.id, status="approved")
        expired = await _quote(db, workspace_id=ws.id, contact_id=contact.id, status="expired")

        answers = [
            await subject_matches_rules(
                db,
                workspace_id=ws.id,
                subject_id=str(q.id),
                rules=rules,
                subject_type="quote",
            )
            for q in (sent, approved, expired)
        ]

        assert answers == [True, False, True]

        await db.rollback()


# --- Behaviour that must not regress ------------------------------------------


async def test_contact_subject_remains_the_default() -> None:
    """Every pre-existing automation keeps working untouched."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        rules = [{"field": "first_name", "operator": "eq", "value": "Dana"}]

        assert await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=contact.id,
            rules=rules,
        )
        # The old entry point still resolves identically.
        assert await contact_matches_rules(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            rules=rules,
        )

        await db.rollback()


async def test_an_empty_condition_still_matches() -> None:
    """A half-built branch carries on down the main path rather than diverting."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, workspace_id=ws.id, contact_id=contact.id)

        assert await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(quote.id),
            rules=[],
            subject_type="quote",
        )

        await db.rollback()


async def test_a_deleted_subject_does_not_match() -> None:
    """A missing record is an answered question, not an ambiguous one.

    Distinct from the empty-rules case above: there the workflow author said
    nothing, so the run proceeds; here the record is gone, so "is this quote
    still unsold?" is definitively no.
    """
    rules = [{"field": "status", "operator": "in", "value": list(REVIVABLE_STATUSES)}]

    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        assert not await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=str(uuid.uuid4()),
            rules=rules,
            subject_type="quote",
        )
        assert not await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id=None,
            rules=rules,
            subject_type="quote",
        )

        await db.rollback()


async def test_an_unknown_subject_type_does_not_stall_the_run() -> None:
    """A workflow naming a subject this build lacks proceeds rather than parking."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        assert await subject_matches_rules(
            db,
            workspace_id=ws.id,
            subject_id="anything",
            rules=[{"field": "status", "operator": "eq", "value": "sent"}],
            subject_type="not_a_real_subject",
        )

        await db.rollback()


async def test_a_subject_in_another_workspace_does_not_match() -> None:
    """Subject lookups stay tenant-scoped."""
    rules = [{"field": "status", "operator": "in", "value": list(REVIVABLE_STATUSES)}]

    async with AsyncSessionLocal() as db:
        owner = await _workspace(db)
        stranger = await _workspace(db)
        contact = await _contact(db, owner.id)
        quote = await _quote(db, workspace_id=owner.id, contact_id=contact.id)

        assert await subject_matches_rules(
            db,
            workspace_id=owner.id,
            subject_id=str(quote.id),
            rules=rules,
            subject_type="quote",
        )
        assert not await subject_matches_rules(
            db,
            workspace_id=stranger.id,
            subject_id=str(quote.id),
            rules=rules,
            subject_type="quote",
        )

        await db.rollback()


async def test_the_remaining_suppression_conditions_are_recorded() -> None:
    """Two of the worker's six stop reasons are still not expressible.

    Kept as an explicit note rather than a silent omission:

    * **replied since last touch** needs a per-step outcome ledger to know when
      the last touch was. That is ``automation_step_runs`` (PR 2).
    * **appointment booked** is a related-entity existence check, which needs an
      ``extra_resolver`` on the quote column map in the same shape
      ``contact_filters`` already uses for tag membership.

    Four of six are expressible here, and those four are the ones that were
    causing sends to customers who had already bought.
    """
    assert SUBJECT_CONTACT == "contact"
