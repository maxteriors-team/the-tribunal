"""Integration tests for the sales-performance query path.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

The maths is covered by ``test_sales_performance_service.py``; what needs a real
database is the *loading*: the creation-date window, tenant isolation, and the
two outer joins that hang a closer name and an attributed lead-source channel
off each quote without dropping quotes that have neither.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.lead_source import LeadSource, LeadSourceType
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline
from app.models.quote import Quote
from app.models.user import User
from app.models.workspace import Workspace
from app.services.reporting import SalesPerformanceService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

WINDOW_FROM = date(2026, 7, 1)
WINDOW_TO = date(2026, 7, 31)
IN_WINDOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Sales", slug=f"sales-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _user(db, *, full_name: str | None) -> User:
    email = f"closer-{uuid.uuid4().hex[:6]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    email = f"lead-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Grace",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _opportunity_on_channel(
    db, workspace_id: uuid.UUID, source_type: LeadSourceType
) -> Opportunity:
    """An opportunity carrying the attribution snapshot ROI reporting reads."""
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    lead_source = LeadSource(
        workspace_id=workspace_id, name=source_type.value, source_type=source_type
    )
    db.add(lead_source)
    await db.flush()

    opportunity = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        name="Deal",
        lead_source_id=lead_source.id,
    )
    db.add(opportunity)
    await db.flush()
    return opportunity


async def _quote(
    db,
    workspace_id: uuid.UUID,
    *,
    status: str,
    total: float,
    created_at: datetime = IN_WINDOW,
    attach_count: int = 0,
    attach_value: float = 0.0,
    primary_service: str | None = None,
    created_by_id: int | None = None,
    opportunity_id: uuid.UUID | None = None,
    currency: str = "USD",
) -> Quote:
    quote = Quote(
        workspace_id=workspace_id,
        number=f"QUO-{uuid.uuid4().hex[:6]}",
        subtotal=total,
        total=total,
        currency=currency,
        status=status,
        attach_count=attach_count,
        attach_value=attach_value,
        primary_service=primary_service,
        created_by_id=created_by_id,
        opportunity_id=opportunity_id,
        created_at=created_at,
    )
    db.add(quote)
    await db.flush()
    return quote


async def _report(db, workspace_id: uuid.UUID):
    return await SalesPerformanceService(db).sales_performance(
        workspace_id, date_from=WINDOW_FROM, date_to=WINDOW_TO
    )


async def test_reports_metrics_for_quotes_created_in_the_window() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _quote(db, ws.id, status="approved", total=4_000, attach_count=1, attach_value=500)
        await _quote(db, ws.id, status="approved", total=6_000)
        await _quote(db, ws.id, status="declined", total=9_000)
        await _quote(db, ws.id, status="sent", total=9_000)
        await _quote(db, ws.id, status="draft", total=9_999)

        report = await _report(db, ws.id)

        assert report.quotes_issued == 4  # the draft never counts
        assert report.quotes_approved == 2
        assert report.revenue_approved == 10_000.0
        assert report.avg_job_value == 5_000.0
        assert report.median_job_value == 5_000.0
        assert report.attach_rate == 0.5
        assert report.avg_attach_value == 500.0
        # 2 approved / (2 approved + 1 declined); the sent quote is undecided.
        assert report.close_rate == 0.6667


async def test_window_excludes_quotes_created_outside_it() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _quote(db, ws.id, status="approved", total=1_000)
        # Boundary days must be *inside* the inclusive window...
        await _quote(
            db,
            ws.id,
            status="approved",
            total=2_000,
            created_at=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
        )
        await _quote(
            db,
            ws.id,
            status="approved",
            total=4_000,
            created_at=datetime(2026, 7, 1, 0, 0, tzinfo=UTC),
        )
        # ...and the neighbouring months must not leak in.
        await _quote(
            db,
            ws.id,
            status="approved",
            total=99_000,
            created_at=datetime(2026, 6, 30, 23, 59, tzinfo=UTC),
        )
        await _quote(
            db,
            ws.id,
            status="approved",
            total=99_000,
            created_at=datetime(2026, 8, 1, 0, 0, tzinfo=UTC),
        )

        report = await _report(db, ws.id)

        assert report.quotes_approved == 3
        assert report.revenue_approved == 7_000.0


async def test_another_workspaces_quotes_never_leak_in() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        await _quote(db, ws.id, status="approved", total=1_000)
        await _quote(db, other.id, status="approved", total=50_000)

        report = await _report(db, ws.id)

        assert report.quotes_issued == 1
        assert report.revenue_approved == 1_000.0


async def test_breakdowns_join_closer_and_attributed_lead_source() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        closer = await _user(db, full_name="Ada Closer")
        google = await _opportunity_on_channel(db, ws.id, LeadSourceType.GOOGLE_ADS)

        await _quote(
            db,
            ws.id,
            status="approved",
            total=8_000,
            primary_service="roof",
            created_by_id=closer.id,
            opportunity_id=google.id,
        )
        # No user, no opportunity: must still appear, in the fallback buckets.
        await _quote(db, ws.id, status="approved", total=2_000)

        report = await _report(db, ws.id)

        by_closer = {row.label: row for row in report.by_closer}
        assert by_closer["Ada Closer"].key == str(closer.id)
        assert by_closer["Ada Closer"].revenue_approved == 8_000.0
        assert by_closer["Unassigned"].revenue_approved == 2_000.0

        by_source = {row.label: row for row in report.by_lead_source}
        assert by_source["Google Ads"].revenue_approved == 8_000.0
        assert by_source["Unattributed"].revenue_approved == 2_000.0

        by_service = {row.label: row for row in report.by_primary_service}
        assert by_service["roof"].revenue_approved == 8_000.0
        assert by_service["Uncategorized"].revenue_approved == 2_000.0


async def test_empty_workspace_reports_nulls() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        report = await _report(db, ws.id)

        assert report.quotes_issued == 0
        assert report.avg_job_value is None
        assert report.close_rate is None
        assert report.attach_rate is None
        assert report.by_closer == []


async def test_refuses_to_report_across_currencies() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _quote(db, ws.id, status="approved", total=1_000, currency="USD")
        await _quote(db, ws.id, status="approved", total=2_000, currency="EUR")

        # Same failure mode as AR aging / job P&L: refuse, never silently sum.
        with pytest.raises(HTTPException) as exc:
            await _report(db, ws.id)

        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Conversion rate — a contact cohort, not a quote cohort
# ---------------------------------------------------------------------------


async def _won_deal_for(db, workspace_id: uuid.UUID, contact_id: int) -> Opportunity:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    await db.flush()
    opportunity = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        primary_contact_id=contact_id,
        name="Deal",
        status="won",
    )
    db.add(opportunity)
    await db.flush()
    return opportunity


async def _contact_created_at(db, workspace_id: uuid.UUID, created_at: datetime) -> Contact:
    contact = await _contact(db, workspace_id)
    contact.created_at = created_at
    await db.flush()
    return contact


async def test_conversion_counts_won_contacts_over_the_created_cohort() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        won = await _contact_created_at(db, ws.id, IN_WINDOW)
        await _won_deal_for(db, ws.id, won.id)
        await _contact_created_at(db, ws.id, IN_WINDOW)  # still open
        await _contact_created_at(db, ws.id, IN_WINDOW)  # still open
        # Created before the window: neither numerator nor denominator.
        outside = await _contact_created_at(db, ws.id, datetime(2026, 6, 1, tzinfo=UTC))
        await _won_deal_for(db, ws.id, outside.id)

        report = await _report(db, ws.id)

        assert report.contacts_created == 3
        assert report.contacts_converted == 1
        assert report.conversion_rate == 0.3333


async def test_conversion_is_null_for_a_window_with_no_new_contacts() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _contact_created_at(db, ws.id, datetime(2026, 5, 1, tzinfo=UTC))

        report = await _report(db, ws.id)

        assert report.contacts_created == 0
        assert report.conversion_rate is None


async def test_conversion_ignores_another_workspaces_won_deals() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact_created_at(db, ws.id, IN_WINDOW)
        # A won deal filed under a different tenant must not convert this contact.
        await _won_deal_for(db, other.id, contact.id)

        report = await _report(db, ws.id)

        assert report.contacts_created == 1
        assert report.contacts_converted == 0
        assert report.conversion_rate == 0.0


async def test_open_and_lost_deals_do_not_count_as_conversions() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact_created_at(db, ws.id, IN_WINDOW)
        deal = await _won_deal_for(db, ws.id, contact.id)
        deal.status = "lost"
        await db.flush()

        report = await _report(db, ws.id)

        assert report.contacts_converted == 0


# ---------------------------------------------------------------------------
# Stale statuses — a lapsed quote is decided, not still out
# ---------------------------------------------------------------------------


async def test_lapsed_sent_quote_counts_as_expired_without_a_sweep() -> None:
    """No worker flips ``sent`` -> ``expired``; the report must not be fooled.

    ``_expire_overdue`` only runs on quote *read* paths, so a quote whose
    expiry date passed can sit in ``sent`` for days. Counting it as undecided
    would keep it out of the close-rate denominator and inflate the rate.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _quote(db, ws.id, status="approved", total=1_000)
        lapsed = await _quote(db, ws.id, status="sent", total=2_000)
        lapsed.expiry_date = date(2026, 7, 20)  # inside the window, already past
        await db.flush()

        report = await _report(db, ws.id)

        # 1 approved / (1 approved + 1 expired) — not 100% off a lone approval.
        assert report.close_rate == 0.5
        # The stored row is untouched: reporting is a GET and must not write.
        await db.refresh(lapsed)
        assert lapsed.status == "sent"


async def test_sent_quote_inside_its_validity_window_stays_undecided() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        await _quote(db, ws.id, status="approved", total=1_000)
        still_out = await _quote(db, ws.id, status="sent", total=2_000)
        still_out.expiry_date = date.today() + timedelta(days=30)
        await db.flush()

        report = await _report(db, ws.id)

        assert report.close_rate == 1.0


# ---------------------------------------------------------------------------
# Show-up rate — appointments booked in the window
# ---------------------------------------------------------------------------


async def _appointment(
    db,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    status: str,
    scheduled_at: datetime = IN_WINDOW,
) -> Appointment:
    appointment = Appointment(
        workspace_id=workspace_id,
        contact_id=contact_id,
        scheduled_at=scheduled_at,
        status=status,
    )
    db.add(appointment)
    await db.flush()
    return appointment


async def test_show_up_rate_counts_only_decided_appointments() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _appointment(db, ws.id, contact.id, status="completed")
        await _appointment(db, ws.id, contact.id, status="completed")
        await _appointment(db, ws.id, contact.id, status="completed")
        await _appointment(db, ws.id, contact.id, status="no_show")
        # Neither of these is a decision about attendance.
        await _appointment(db, ws.id, contact.id, status="scheduled")
        await _appointment(db, ws.id, contact.id, status="cancelled")

        report = await _report(db, ws.id)

        assert report.appointments_completed == 3
        assert report.appointments_no_show == 1
        assert report.show_up_rate == 0.75


async def test_show_up_rate_is_null_when_nothing_was_marked() -> None:
    """The state every workspace starts in: booked, but never marked."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _appointment(db, ws.id, contact.id, status="scheduled")
        await _appointment(db, ws.id, contact.id, status="scheduled")

        report = await _report(db, ws.id)

        assert report.show_up_rate is None


async def test_show_up_rate_excludes_appointments_outside_the_window() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _appointment(db, ws.id, contact.id, status="completed")
        await _appointment(
            db,
            ws.id,
            contact.id,
            status="no_show",
            scheduled_at=datetime(2026, 6, 15, tzinfo=UTC),
        )

        report = await _report(db, ws.id)

        assert report.appointments_completed == 1
        assert report.appointments_no_show == 0
        assert report.show_up_rate == 1.0


async def test_another_workspaces_appointments_never_leak_in() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        other_contact = await _contact(db, other.id)
        await _appointment(db, ws.id, contact.id, status="completed")
        await _appointment(db, other.id, other_contact.id, status="no_show")

        report = await _report(db, ws.id)

        assert report.appointments_no_show == 0
        assert report.show_up_rate == 1.0
