"""Approving a quote provisions the Service Plans the client signed up for.

Before this, a Care Plan lived only as a tier key buried in
``quote.proposal_document`` and a Christmas signup produced no recurring work at
all — nothing recorded that *this client is on Gold* or that someone has to hang
their lights every November. These tests pin that record: the Care Plan's tier
and visit cadence, the Christmas install + takedown pair anchored on the
workspace's configured season, the quiet no-op for a flat install-only quote,
and the idempotency that makes re-approving a quote (an operator retry, a client
double-clicking the public approve button) provision nothing new.

Marked ``integration`` (Postgres: JSONB documents plus the partial unique index
that is the authoritative anti-double-signup guard). Run with ``-m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.quote import Quote
from app.models.recurring_job import (
    RecurrenceFrequency,
    RecurringJobTemplate,
    ServicePlanType,
)
from app.models.workspace import Workspace
from app.services.quotes import QuoteService
from app.services.recurring_jobs import ServicePlanProvisioner

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# A season the operator configured away from the defaults, so a passing test
# proves the anchors are read from config rather than hardcoded.
SEASON = {
    "season_install_month": 10,
    "season_install_day": 20,
    "season_takedown_month": 2,
    "season_takedown_day": 3,
}

SIGNED_AT = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
# Frozen clock so cursors are deterministic regardless of when the suite runs.
NOW = SIGNED_AT


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db: AsyncSession, *, christmas: dict[str, Any] | None = None) -> Workspace:
    settings: dict[str, Any] = {}
    if christmas is not None:
        settings["pricing"] = {"christmas": {"enabled": True, **christmas}}
    ws = Workspace(
        id=uuid.uuid4(),
        name="Service Plans",
        slug=f"plans-{uuid.uuid4().hex[:8]}",
        settings=settings,
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    email = f"grace-{uuid.uuid4().hex[:6]}@example.com"
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


async def _quote(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int | None,
    document: dict[str, Any] | None,
    *,
    status: str = "approved",
) -> Quote:
    quote = Quote(
        workspace_id=workspace_id,
        contact_id=contact_id,
        number=f"QUO-{uuid.uuid4().int % 1_000_000:06d}",
        status=status,
        currency="USD",
        subtotal=4200,
        tax_amount=0,
        discount_amount=0,
        total=4200,
        approved_at=SIGNED_AT if status == "approved" else None,
        proposal_document=document,
    )
    db.add(quote)
    await db.flush()
    return quote


def _care_plan_document(selected: str | None, *, visits: int = 4) -> dict[str, Any]:
    return {
        "care_plan": {
            "fixture_count": 24,
            "free_fixtures": 10,
            "options": [
                {
                    "key": "silver",
                    "name": "Silver",
                    "price": 480,
                    "savings": 0,
                    "visits": 1,
                    "repair_discount": 0.1,
                },
                {
                    "key": "gold",
                    "name": "Gold",
                    "price": 960,
                    "savings": 0,
                    "visits": visits,
                    "repair_discount": 0.2,
                },
            ],
            "selected": selected,
        }
    }


def _christmas_document(
    label: str = "Holiday Lighting",
    **section_overrides: Any,
) -> dict[str, Any]:
    """A seasonal signup snapshot.

    ``section_overrides`` sets the seasonal service flags (``takedown`` /
    ``storage``). Omitting them mirrors a document written before those fields
    existed, which must keep provisioning exactly as it always did.
    """
    section: dict[str, Any] = {
        "key": "christmas",
        "label": label,
        "lines": [],
        "financed_total": 2400,
    }
    section.update(section_overrides)
    return {"categories": ["christmas"], "category_sections": [section]}


async def _plans(db: AsyncSession, quote_id: uuid.UUID) -> list[RecurringJobTemplate]:
    rows = (
        (
            await db.execute(
                select(RecurringJobTemplate)
                .where(RecurringJobTemplate.source_quote_id == quote_id)
                .order_by(RecurringJobTemplate.next_run_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Care Plan
# --------------------------------------------------------------------------- #
async def test_selected_care_plan_becomes_a_tiered_service_plan() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _care_plan_document("gold"))

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert len(created) == 1
        plan = created[0]
        assert plan.plan_type == ServicePlanType.LIGHTING_CARE_PLAN
        # The tier the client actually picked is now a queryable field, not a
        # string buried in JSONB.
        assert plan.care_plan_tier == "gold"
        assert plan.title == "Care Plan — Gold"
        assert plan.contact_id == contact.id
        assert plan.source_quote_id == quote.id
        assert plan.is_active is True
        # 4 visits a year = every 3 months, first visit one period after signup
        # (the install comes first, maintenance follows).
        assert plan.frequency == RecurrenceFrequency.MONTHLY
        assert plan.interval == 3
        assert plan.next_run_at == datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


async def test_single_visit_care_plan_recurs_yearly() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _care_plan_document("gold", visits=1))

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert len(created) == 1
        assert created[0].frequency == RecurrenceFrequency.YEARLY
        assert created[0].interval == 1
        assert created[0].next_run_at == datetime(2027, 7, 15, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Christmas: install + takedown pair
# --------------------------------------------------------------------------- #
async def test_christmas_signup_creates_install_and_takedown_plans() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _christmas_document())

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert len(created) == 2
        install, takedown = sorted(created, key=lambda plan: plan.next_run_at)
        assert install.title == "Holiday Lighting — Install"
        assert takedown.title == "Holiday Lighting — Takedown"
        assert {install.plan_type, takedown.plan_type} == {ServicePlanType.CHRISTMAS_LIGHTS}
        # A Christmas plan sells no maintenance tier, so it must not display one.
        assert install.care_plan_tier is None
        assert takedown.care_plan_tier is None

        # Anchored on the workspace's configured season, both repeating yearly.
        assert install.next_run_at.date() == datetime(2026, 10, 20, tzinfo=UTC).date()
        assert install.frequency == RecurrenceFrequency.YEARLY
        assert install.interval == 1
        # Takedown belongs to the season just installed — the following
        # February, never the anchor that already passed this year.
        assert takedown.next_run_at.date() == datetime(2027, 2, 3, tzinfo=UTC).date()
        assert takedown.frequency == RecurrenceFrequency.YEARLY


async def test_christmas_install_rolls_to_next_year_when_the_season_has_passed() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _christmas_document())
        # Signed after this year's install anchor (Oct 20) already passed.
        quote.approved_at = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        install, takedown = sorted(created, key=lambda plan: plan.next_run_at)
        assert install.next_run_at.date() == datetime(2027, 10, 20, tzinfo=UTC).date()
        assert takedown.next_run_at.date() == datetime(2028, 2, 3, tzinfo=UTC).date()


async def test_declining_takedown_provisions_only_the_install() -> None:
    """A crew must not be dispatched every January for work nobody bought."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _christmas_document(takedown=False))

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert [plan.title for plan in created] == ["Holiday Lighting — Install"]
        assert created[0].next_run_at.date() == datetime(2026, 10, 20, tzinfo=UTC).date()


async def test_buying_takedown_still_provisions_the_pair() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _christmas_document(takedown=True))

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert sorted(plan.title for plan in created) == [
            "Holiday Lighting — Install",
            "Holiday Lighting — Takedown",
        ]


async def test_a_signup_sold_before_the_flag_existed_keeps_its_takedown() -> None:
    """An absent flag means unknown, never declined.

    Quotes approved before the seasonal service flags shipped record nothing.
    Reading that silence as "declined" would quietly strip the takedown crew off
    every season already sold.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _christmas_document())

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert len(created) == 2


async def test_selling_storage_tells_both_crews_about_the_bins() -> None:
    """Storage is billed; the crews holding the decor have to know it."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(
            db, ws.id, contact.id, _christmas_document(takedown=True, storage=True)
        )

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        install, takedown = sorted(created, key=lambda plan: plan.next_run_at)
        assert "pull their decor before the visit" in (install.description or "")
        assert "bring bins" in (takedown.description or "")


async def test_without_storage_the_descriptions_stay_unchanged() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        quote = await _quote(
            db, ws.id, contact.id, _christmas_document(takedown=True, storage=False)
        )

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert all("bins" not in (plan.description or "") for plan in created)


async def test_christmas_season_falls_back_to_defaults_without_pricing_config() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)  # no pricing block at all
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _christmas_document())

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        install, takedown = sorted(created, key=lambda plan: plan.next_run_at)
        assert install.next_run_at.date() == datetime(2026, 11, 15, tzinfo=UTC).date()
        assert takedown.next_run_at.date() == datetime(2027, 1, 8, tzinfo=UTC).date()


async def test_backfilling_an_old_signup_never_schedules_into_the_past() -> None:
    """Replaying an ancient approval must book the next season, not last one.

    The backfill runs this same provisioner over quotes approved before the
    feature existed. Anchoring on their original ``approved_at`` alone would set
    a cursor in the past, and the worker would happily materialize a job dated
    last November onto the dispatch board.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        document = {**_care_plan_document("gold"), **_christmas_document()}
        quote = await _quote(db, ws.id, contact.id, document)
        quote.approved_at = datetime(2024, 3, 2, 9, 0, tzinfo=UTC)  # two seasons ago

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert len(created) == 3
        assert all(plan.next_run_at > NOW for plan in created)
        christmas = sorted(
            (p for p in created if p.plan_type == ServicePlanType.CHRISTMAS_LIGHTS),
            key=lambda plan: plan.next_run_at,
        )
        assert christmas[0].next_run_at.date() == datetime(2026, 10, 20, tzinfo=UTC).date()
        assert christmas[1].next_run_at.date() == datetime(2027, 2, 3, tzinfo=UTC).date()


async def test_care_plan_and_christmas_on_one_quote_provision_together() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        document = {**_care_plan_document("gold"), **_christmas_document()}
        quote = await _quote(db, ws.id, contact.id, document)

        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)

        assert len(created) == 3
        assert sum(p.plan_type == ServicePlanType.LIGHTING_CARE_PLAN for p in created) == 1
        assert sum(p.plan_type == ServicePlanType.CHRISTMAS_LIGHTS for p in created) == 2


# --------------------------------------------------------------------------- #
# No-ops
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "document",
    [
        pytest.param(None, id="no_proposal_document"),
        pytest.param({}, id="empty_document"),
        pytest.param(_care_plan_document(None), id="care_plan_offered_but_not_selected"),
        pytest.param({"categories": ["landscape"], "category_sections": []}, id="landscape_only"),
    ],
)
async def test_quote_without_a_signup_provisions_nothing(document: dict[str, Any] | None) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, document)

        assert await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW) == []
        assert await _plans(db, quote.id) == []


async def test_quote_without_a_contact_provisions_nothing() -> None:
    """A plan needs a customer; a contactless quote is skipped, not a 500."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        quote = await _quote(db, ws.id, None, _care_plan_document("gold"))

        assert await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW) == []


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
async def test_reprovisioning_the_same_quote_creates_nothing_new() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        document = {**_care_plan_document("gold"), **_christmas_document()}
        quote = await _quote(db, ws.id, contact.id, document)
        provisioner = ServicePlanProvisioner(db)

        first = await provisioner.provision_from_quote(quote, now=NOW)
        second = await provisioner.provision_from_quote(quote, now=NOW)

        assert len(first) == 3
        assert second == []
        assert len(await _plans(db, quote.id)) == 3


async def test_the_unique_index_rejects_a_duplicate_plan() -> None:
    """The database — not the pre-check — is what guarantees one signup.

    Two concurrent approvals both pass the in-process "already provisioned?"
    read, so the partial unique index has to be the thing that stops the second
    insert.
    """
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        quote = await _quote(db, ws.id, contact.id, _care_plan_document("gold"))
        created = await ServicePlanProvisioner(db).provision_from_quote(quote, now=NOW)
        original = created[0]

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(
                    RecurringJobTemplate(
                        workspace_id=ws.id,
                        contact_id=contact.id,
                        source_quote_id=quote.id,
                        plan_type=original.plan_type,
                        title=original.title,
                        frequency=str(RecurrenceFrequency.MONTHLY),
                        next_run_at=SIGNED_AT,
                    )
                )
                await db.flush()


# --------------------------------------------------------------------------- #
# The approve path itself
# --------------------------------------------------------------------------- #
async def test_approving_a_quote_signs_the_client_up() -> None:
    """End to end through ``QuoteService.approve_quote`` (which commits)."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, christmas=SEASON)
        contact = await _contact(db, ws.id)
        document = {**_care_plan_document("gold"), **_christmas_document()}
        quote = await _quote(db, ws.id, contact.id, document, status="draft")
        await db.commit()
        quote_id = quote.id
        workspace_id = ws.id

    try:
        async with AsyncSessionLocal() as db:
            approved = await QuoteService(db).approve_quote(workspace_id, quote_id)
            assert approved.status == "approved"
            plans = await _plans(db, quote_id)
            assert [plan.plan_type for plan in plans].count(
                ServicePlanType.CHRISTMAS_LIGHTS
            ) == 2
            assert any(plan.care_plan_tier == "gold" for plan in plans)

        # Re-approving is idempotent at the plan level too.
        async with AsyncSessionLocal() as db:
            await QuoteService(db).approve_quote(workspace_id, quote_id)
            assert len(await _plans(db, quote_id)) == 3
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(RecurringJobTemplate).where(
                    RecurringJobTemplate.workspace_id == workspace_id
                )
            )
            await db.execute(delete(Quote).where(Quote.workspace_id == workspace_id))
            await db.execute(delete(Contact).where(Contact.workspace_id == workspace_id))
            await db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await db.commit()
