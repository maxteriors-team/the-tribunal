"""Real-DB integration tests for :class:`QuoteService`.

These hit Postgres (the per-workspace number sequence, the named ``quote_status``
enum, lazy expiry via a scoped UPDATE, and conversion into real ``Job`` /
``Invoice`` rows behave differently under a real engine than under mocks), so
they are marked ``integration`` and deselected by default. Run with
``pytest -m integration``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import (
    Crew,
    Job,
    JobAssignment,
    ServiceLocation,
    Technician,
)
from app.models.invoice import Invoice
from app.models.lighting_project import LightingProject
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline
from app.models.quote import Quote
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.attach_rules import (
    AttachDismissalRequest,
    AttachRule,
    AttachRulesSettings,
)
from app.schemas.estimate import EstimateQuoteRequest
from app.schemas.pricing import (
    ChristmasConfig,
    FinancingConfig,
    PermanentConfig,
    PricingSettings,
)
from app.schemas.quote import (
    QuoteCreate,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteUpdate,
)
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.services.jobs import JobService
from app.services.quotes import QuoteService
from app.services.quotes.attach_rules_config import SETTINGS_KEY as ATTACH_RULES_KEY

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Quotes Co", slug=f"quo-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _make_member(
    db: AsyncSession, workspace_id: uuid.UUID, *, name: str = "Sales Owner"
) -> User:
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name=name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role="sales_rep"))
    await db.flush()
    return user


async def _make_contact(
    db: AsyncSession, workspace_id: uuid.UUID, *, email: str | None = None
) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Pat",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email) if email else None,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _make_location(
    db: AsyncSession, workspace_id: uuid.UUID, contact_id: int
) -> ServiceLocation:
    loc = ServiceLocation(workspace_id=workspace_id, contact_id=contact_id, name="Main House")
    db.add(loc)
    await db.flush()
    return loc


def _permanent_project_document() -> dict[str, object]:
    return {
        "version": 2,
        "projectType": "permanent",
        "activeShotId": "front",
        "shots": [
            {
                "id": "front",
                "photo": {
                    "dataUrl": "data:image/png;base64,AAAA",
                    "width": 1200,
                    "height": 800,
                },
                "design": {
                    "runs": [],
                    "items": [
                        {
                            "id": "fixture-1",
                            "productId": "product-1",
                            "at": {"x": 100, "y": 120},
                            "sizePx": 24,
                        }
                    ],
                    "calibration": None,
                },
                "dusk": 0.4,
            }
        ],
        "updatedAt": "2026-08-27T12:00:00.000Z",
    }


async def _make_catalog_item(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    name: str,
    unit_price: float,
    service_category: str | None,
) -> CatalogItem:
    item = CatalogItem(
        workspace_id=workspace_id,
        name=name,
        unit_price=unit_price,
        service_category=service_category,
    )
    db.add(item)
    await db.flush()
    return item


async def test_create_computes_totals_and_allocates_number() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)

        created = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Backyard lighting",
                tax_amount=10.0,
                discount_amount=5.0,
                line_items=[
                    QuoteLineItemCreate(name="Labor", quantity=2, unit_price=100.0),
                    QuoteLineItemCreate(name="Parts", quantity=1, unit_price=50.0, discount=5.0),
                ],
            ),
            created_by_id=None,
        )

        # subtotal = (2*100) + (1*50 - 5) = 245; total = 245 + 10 - 5 = 250
        assert created.subtotal == 245.0
        assert created.total == 250.0
        assert created.status == "draft"
        assert created.title == "Backyard lighting"
        assert created.number == "QUO-000001"
        assert len(created.line_items) == 2

        second = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)
        assert second.number == "QUO-000002"


async def test_quote_defaults_to_creator_and_can_reassign_after_decision() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other_ws = await _make_workspace(db)
        creator = await _make_member(db, ws.id, name="Creator")
        foreign = await _make_member(db, other_ws.id, name="Foreign owner")
        service = QuoteService(db)

        created = await service.create_quote(
            ws.id, QuoteCreate(line_items=[]), created_by_id=creator.id
        )
        assert created.assigned_user_id == creator.id
        assert created.assignee is not None
        assert created.assignee.full_name == "Creator"

        stored = await db.get(Quote, created.id)
        assert stored is not None
        stored.status = "approved"
        await db.flush()

        cleared = await service.assign_quote(ws.id, created.id, None)
        assert cleared.assigned_user_id is None
        assert cleared.assignee is None

        with pytest.raises(NotFoundError):
            await service.assign_quote(ws.id, created.id, foreign.id)


async def test_quote_inherits_active_opportunity_owner() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        creator = await _make_member(db, ws.id, name="Creator")
        owner = await _make_member(db, ws.id, name="Deal owner")
        pipeline = Pipeline(workspace_id=ws.id, name="Sales")
        db.add(pipeline)
        await db.flush()
        opportunity = Opportunity(
            workspace_id=ws.id,
            pipeline_id=pipeline.id,
            name="Roof replacement",
            assigned_user_id=owner.id,
        )
        db.add(opportunity)
        await db.flush()

        created = await QuoteService(db).create_quote(
            ws.id,
            QuoteCreate(opportunity_id=opportunity.id, line_items=[]),
            created_by_id=creator.id,
        )

        assert created.assigned_user_id == owner.id
        assert created.assignee is not None
        assert created.assignee.full_name == "Deal owner"


async def test_number_sequence_is_per_workspace() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        svc = QuoteService(db)

        a1 = await svc.create_quote(ws_a.id, QuoteCreate(line_items=[]))
        b1 = await svc.create_quote(ws_b.id, QuoteCreate(line_items=[]))

        assert a1.number == "QUO-000001"
        assert b1.number == "QUO-000001"


async def test_line_item_edits_recompute_totals() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(line_items=[QuoteLineItemCreate(name="Base", unit_price=100.0)]),
        )
        assert quote.total == 100.0

        quote = await svc.add_line_item(
            ws.id, quote.id, QuoteLineItemCreate(name="Extra", quantity=3, unit_price=10.0)
        )
        assert quote.total == 130.0

        extra = next(li for li in quote.line_items if li.name == "Extra")
        quote = await svc.update_line_item(
            ws.id, quote.id, extra.id, QuoteLineItemUpdate(quantity=5)
        )
        assert next(li for li in quote.line_items if li.name == "Extra").total == 50.0
        assert quote.total == 150.0

        base = next(li for li in quote.line_items if li.name == "Base")
        quote = await svc.remove_line_item(ws.id, quote.id, base.id)
        assert len(quote.line_items) == 1
        assert quote.total == 50.0


async def test_catalog_lines_denormalize_attach_metrics_on_every_save() -> None:
    """Picking price-book items snapshots their category and keeps the quote's
    attach metrics current across create, add, update and remove."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        gutters = await _make_catalog_item(db, ws.id, "Gutter Guard", 1200.0, "gutters")
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[
                    QuoteLineItemCreate(
                        name="Roof Replacement", unit_price=9000.0, catalog_item_id=roof.id
                    )
                ]
            ),
        )
        # One service on the quote: it's a roof job with nothing attached.
        assert quote.primary_service == "roof"
        assert quote.attach_count == 0
        assert quote.attach_value == 0.0
        assert quote.line_items[0].service_category == "roof"

        quote = await svc.add_line_item(
            ws.id,
            quote.id,
            QuoteLineItemCreate(name="Gutter Guard", unit_price=1200.0, catalog_item_id=gutters.id),
        )
        assert quote.primary_service == "roof"
        assert quote.attach_count == 1
        assert quote.attach_value == 1200.0

        # A hand-typed line has no category: it lifts the total but is not an
        # attachment, so attach_value is never just "total minus primary".
        quote = await svc.add_line_item(
            ws.id, quote.id, QuoteLineItemCreate(name="Custom fascia", unit_price=400.0)
        )
        assert quote.total == 10600.0
        assert quote.attach_count == 1
        assert quote.attach_value == 1200.0

        # Repricing a line re-derives the metrics rather than leaving them stale.
        gutter_line = next(li for li in quote.line_items if li.name == "Gutter Guard")
        quote = await svc.update_line_item(
            ws.id, quote.id, gutter_line.id, QuoteLineItemUpdate(quantity=2)
        )
        assert quote.attach_value == 2400.0

        quote = await svc.remove_line_item(ws.id, quote.id, gutter_line.id)
        assert quote.primary_service == "roof"
        assert quote.attach_count == 0
        assert quote.attach_value == 0.0


async def test_catalog_item_from_another_workspace_leaves_line_uncategorized() -> None:
    """A tenant must not be able to read (or borrow) another workspace's
    categories by guessing a catalog item id."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other = await _make_workspace(db)
        foreign = await _make_catalog_item(db, other.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[
                    QuoteLineItemCreate(
                        name="Roof Replacement", unit_price=9000.0, catalog_item_id=foreign.id
                    )
                ]
            ),
        )

        assert quote.line_items[0].service_category is None
        assert quote.primary_service is None
        assert quote.attach_count == 0
        assert quote.attach_value == 0.0


# --------------------------------------------------------------------------- #
# Attach rules (the cross-sell prompt enforced at save time)
# --------------------------------------------------------------------------- #
async def _attach_workspace(db: AsyncSession, **rule: object) -> Workspace:
    """A workspace with a single roof -> gutters attach rule."""
    ws = await _make_workspace(db)
    ws.settings = {
        ATTACH_RULES_KEY: AttachRulesSettings(
            rules=[
                AttachRule(
                    primary_category="roof",
                    suggested_categories=["gutters"],
                    **rule,  # type: ignore[arg-type]
                )
            ]
        ).model_dump(mode="json")
    }
    await db.flush()
    return ws


async def _count_quotes(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    result = await db.execute(select(Quote).where(Quote.workspace_id == workspace_id))
    return len(result.scalars().all())


def _roof_only(roof: CatalogItem, **extra: object) -> QuoteCreate:
    return QuoteCreate(
        line_items=[
            QuoteLineItemCreate(name=roof.name, unit_price=9000.0, catalog_item_id=roof.id)
        ],
        **extra,  # type: ignore[arg-type]
    )


async def test_advisory_rule_warns_but_still_saves() -> None:
    """Advisory is the shipped default: it prompts, it never costs the rep a save."""
    async with AsyncSessionLocal() as db:
        ws = await _attach_workspace(db, mode="advisory")
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        quote = await svc.create_quote(ws.id, _roof_only(roof))

        assert quote.attach_warning is not None
        assert quote.attach_warning.mode == "advisory"
        assert quote.attach_warning.suggested_categories == ["gutters"]
        # Saved, not rejected, and nothing was recorded as declined.
        assert quote.status == "draft"
        assert quote.attach_dismissals == []


async def test_satisfied_rule_returns_no_warning() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _attach_workspace(db, mode="blocking")
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        gutters = await _make_catalog_item(db, ws.id, "Gutter Guard", 1200.0, "gutters")
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[
                    QuoteLineItemCreate(
                        name="Roof Replacement", unit_price=9000.0, catalog_item_id=roof.id
                    ),
                    QuoteLineItemCreate(
                        name="Gutter Guard", unit_price=1200.0, catalog_item_id=gutters.id
                    ),
                ]
            ),
        )

        assert quote.attach_warning is None
        assert quote.attach_count == 1


async def test_blocking_rule_rejects_the_save_and_persists_nothing() -> None:
    """A rejected save must leave no quote behind, or the rep gets a ghost draft."""
    async with AsyncSessionLocal() as db:
        ws = await _attach_workspace(db, mode="blocking")
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        with pytest.raises(ValidationError) as excinfo:
            await svc.create_quote(ws.id, _roof_only(roof))

        # The structured warning rides along so the builder can render the same
        # "Add gutters" affordance it would for an advisory prompt.
        assert excinfo.value.details["suggested_categories"] == ["gutters"]
        assert (await _count_quotes(db, ws.id)) == 0


async def test_blocking_rule_saves_once_a_dismissal_reason_is_supplied() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _attach_workspace(db, mode="blocking")
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            _roof_only(roof, attach_dismissal=AttachDismissalRequest(reason="Already has")),
        )

        assert quote.attach_warning is None
        # Recorded, so "asked and declined" is distinguishable from "never asked".
        assert len(quote.attach_dismissals) == 1
        dismissal = quote.attach_dismissals[0]
        assert dismissal.primary_service == "roof"
        assert dismissal.categories == ["gutters"]
        assert dismissal.reason == "Already has"
        assert dismissal.dismissed_at is not None


async def test_dismissal_without_a_reason_is_rejected_when_required() -> None:
    """An unreportable dismissal is the exact thing this feature exists to fix."""
    async with AsyncSessionLocal() as db:
        ws = await _attach_workspace(db, mode="advisory")
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        with pytest.raises(ValidationError):
            await svc.create_quote(
                ws.id, _roof_only(roof, attach_dismissal=AttachDismissalRequest(reason="  "))
            )

        assert (await _count_quotes(db, ws.id)) == 0


async def test_reasonless_dismissal_allowed_when_workspace_does_not_require_one() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        ws.settings = {
            ATTACH_RULES_KEY: AttachRulesSettings(
                rules=[AttachRule(primary_category="roof", suggested_categories=["gutters"])],
                require_dismissal_reason=False,
            ).model_dump(mode="json")
        }
        await db.flush()
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id, _roof_only(roof, attach_dismissal=AttachDismissalRequest())
        )

        assert len(quote.attach_dismissals) == 1
        assert quote.attach_dismissals[0].reason is None


async def test_dismissal_is_ignored_when_nothing_was_suggested() -> None:
    """Never invent a "they declined" event for a quote that has the attach."""
    async with AsyncSessionLocal() as db:
        ws = await _attach_workspace(db, mode="advisory")
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        gutters = await _make_catalog_item(db, ws.id, "Gutter Guard", 1200.0, "gutters")
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[
                    QuoteLineItemCreate(
                        name="Roof Replacement", unit_price=9000.0, catalog_item_id=roof.id
                    ),
                    QuoteLineItemCreate(
                        name="Gutter Guard", unit_price=1200.0, catalog_item_id=gutters.id
                    ),
                ],
                attach_dismissal=AttachDismissalRequest(reason="Customer declined"),
            ),
        )

        assert quote.attach_dismissals == []


async def test_corrupt_attach_rules_blob_never_blocks_a_save() -> None:
    """A broken settings row must not stand between a rep and a sold job."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        ws.settings = {ATTACH_RULES_KEY: {"rules": "not-a-list", "enabled": {"nope": True}}}
        await db.flush()
        roof = await _make_catalog_item(db, ws.id, "Roof Replacement", 9000.0, "roof")
        svc = QuoteService(db)

        quote = await svc.create_quote(ws.id, _roof_only(roof))

        # Defaults applied: advisory, so it prompts without ever failing a save.
        assert quote.status == "draft"
        assert quote.attach_warning is not None
        assert quote.attach_warning.mode == "advisory"


async def test_send_sets_status_and_timestamp() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="Job", unit_price=300.0)])
        )

        sent = await svc.mark_sent(ws.id, quote.id)
        assert sent.status == "sent"
        assert sent.sent_at is not None


async def test_send_allocates_public_token_once() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="Job", unit_price=300.0)])
        )
        # Drafts have no token.
        assert quote.public_token is None

        sent = await svc.mark_sent(ws.id, quote.id)
        assert sent.public_token is not None
        first_token = sent.public_token

        # Re-sending is idempotent for the token: a link already in a customer's
        # inbox must keep working.
        resent = await svc.mark_sent(ws.id, quote.id)
        assert resent.public_token == first_token


async def test_approve_and_decline_guards() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)

        q1 = await svc.create_quote(ws.id, QuoteCreate(line_items=[]))
        approved = await svc.approve_quote(ws.id, q1.id)
        assert approved.status == "approved"
        assert approved.approved_at is not None

        # Re-approving is idempotent; declining an approved quote is rejected.
        assert (await svc.approve_quote(ws.id, q1.id)).status == "approved"
        with pytest.raises(ConflictError):
            await svc.decline_quote(ws.id, q1.id, reason="too late")

        q2 = await svc.create_quote(ws.id, QuoteCreate(line_items=[]))
        declined = await svc.decline_quote(ws.id, q2.id, reason="too expensive")
        assert declined.status == "declined"
        assert declined.decline_reason == "too expensive"
        with pytest.raises(ConflictError):
            await svc.approve_quote(ws.id, q2.id)


async def test_create_rejects_another_workspaces_references() -> None:
    """A foreign contact/site/deal id 404s instead of binding to the quote.

    Without this the quote could be emailed/texted to another tenant's contact,
    echoing their decrypted email/phone back in the response.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other = await _make_workspace(db)
        their_contact = await _make_contact(db, other.id)
        their_location = await _make_location(db, other.id, their_contact.id)
        svc = QuoteService(db)

        with pytest.raises(HTTPException) as exc:
            await svc.create_quote(ws.id, QuoteCreate(contact_id=their_contact.id, line_items=[]))
        assert exc.value.status_code == 404

        with pytest.raises(HTTPException) as exc:
            await svc.create_quote(
                ws.id, QuoteCreate(service_location_id=their_location.id, line_items=[])
            )
        assert exc.value.status_code == 404

        # A non-existent id is indistinguishable from a foreign one.
        with pytest.raises(HTTPException) as exc:
            await svc.create_quote(ws.id, QuoteCreate(opportunity_id=uuid.uuid4(), line_items=[]))
        assert exc.value.status_code == 404


async def test_update_rejects_another_workspaces_contact() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other = await _make_workspace(db)
        their_contact = await _make_contact(db, other.id)
        svc = QuoteService(db)
        quote = await svc.create_quote(ws.id, QuoteCreate(line_items=[]))

        with pytest.raises(HTTPException) as exc:
            await svc.update_quote(ws.id, quote.id, QuoteUpdate(contact_id=their_contact.id))
        assert exc.value.status_code == 404

        # The quote is left untouched.
        fetched = await svc.get_quote(ws.id, quote.id)
        assert fetched.contact_id is None


async def test_locked_quote_rejects_edits() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="X", unit_price=10.0)])
        )
        await svc.approve_quote(ws.id, quote.id)

        with pytest.raises(ConflictError):
            await svc.update_quote(ws.id, quote.id, QuoteUpdate(title="changed"))
        with pytest.raises(ConflictError):
            await svc.add_line_item(ws.id, quote.id, QuoteLineItemCreate(name="Y", unit_price=1.0))


async def test_sent_quote_stays_editable_and_deletable() -> None:
    """Sending is not a lock, and the dashboard's edit/delete actions rely on it.

    Only a *decided* quote (approved/declined/expired) is frozen. A sent one is
    live work: the customer asks for another week, or the quote should never
    have gone out at all. This pins the boundary, because tightening
    ``_LOCKED_STATUSES`` to include ``sent`` would leave the row menu offering
    two actions that can only ever return 409.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[QuoteLineItemCreate(name="X", unit_price=10.0)])
        )
        sent = await svc.mark_sent(ws.id, quote.id)
        assert sent.status == "sent"
        assert sent.public_token is not None

        edited = await svc.update_quote(
            ws.id,
            quote.id,
            QuoteUpdate(title="Now with gutters", expiry_date=date.today() + timedelta(days=30)),
        )
        # Editing must not un-send the quote or reissue the customer's link.
        assert edited.title == "Now with gutters"
        assert edited.status == "sent"
        assert edited.public_token == sent.public_token

        # Deleting a quote that already has a public token exercises the
        # line-item cascade on a real engine, which a mocked session cannot.
        await svc.delete_quote(ws.id, quote.id)
        with pytest.raises(HTTPException):
            await svc.get_quote(ws.id, quote.id)


async def test_zero_percentage_clears_a_deposit() -> None:
    """``deposit_percentage=0`` is how a deposit is removed.

    ``update_quote`` skips ``None`` (it means "leave this field alone"), so there
    is no way to null a deposit column back out. 0 is the escape hatch: it
    stores, clears the other mode, and reads back as no deposit at all. The edit
    dialog's "No deposit" option sends exactly this.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[QuoteLineItemCreate(name="Job", unit_price=1000.0)],
                deposit_percentage=25.0,
            ),
        )
        assert quote.deposit_amount == 250.0
        assert quote.deposit_required is True

        cleared = await svc.update_quote(ws.id, quote.id, QuoteUpdate(deposit_percentage=0))
        assert cleared.deposit_amount is None
        assert cleared.deposit_required is False

        # And switching modes leaves exactly one column populated, so the
        # schema's "one deposit mode" validator can never see both.
        fixed = await svc.update_quote(ws.id, quote.id, QuoteUpdate(deposit_amount_fixed=300.0))
        assert fixed.deposit_amount == 300.0
        row = await _orm_quote(db, quote.id)
        assert row.deposit_percentage is None


async def test_expired_quote_surfaces_on_read() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                line_items=[QuoteLineItemCreate(name="Job", unit_price=100.0)],
                expiry_date=date.today() + timedelta(days=7),
            ),
        )
        await svc.mark_sent(ws.id, quote.id)

        # Push the expiry into the past; the next read must flip sent -> expired.
        row = await db.get(Quote, quote.id)
        assert row is not None
        row.expiry_date = date.today() - timedelta(days=1)
        await db.commit()

        fetched = await svc.get_quote(ws.id, quote.id)
        assert fetched.status == "expired"


async def test_convert_creates_job_and_invoice_idempotently() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        location = await _make_location(db, ws.id, contact.id)
        crew = Crew(workspace_id=ws.id, name="Install Crew")
        technician = Technician(workspace_id=ws.id, name="Alex Field")
        db.add_all([crew, technician])
        await db.flush()
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                service_location_id=location.id,
                title="Install lighting",
                tax_amount=20.0,
                line_items=[
                    QuoteLineItemCreate(name="Labor", quantity=2, unit_price=150.0),
                    QuoteLineItemCreate(name="Fixtures", quantity=4, unit_price=25.0),
                ],
            ),
        )
        await svc.approve_quote(ws.id, quote.id)
        start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        end = start + timedelta(hours=3)

        result = await svc.convert_quote(
            ws.id,
            quote.id,
            scheduled_start=start,
            scheduled_end=end,
            crew_id=crew.id,
            technician_ids=[technician.id],
        )
        assert result.job_id is not None
        assert result.invoice_id is not None
        assert result.idempotent_replay is False
        assert result.quote.converted_job_id == result.job_id
        assert result.quote.converted_invoice_id == result.invoice_id

        job = await db.get(Job, result.job_id)
        assert job is not None
        assert job.title == "Install lighting"
        assert job.contact_id == contact.id
        assert job.service_location_id == location.id
        assert job.crew_id == crew.id
        assert job.source_quote_id == quote.id
        assignments = (
            (await db.execute(select(JobAssignment).where(JobAssignment.job_id == job.id)))
            .scalars()
            .all()
        )
        assert {assignment.technician_id for assignment in assignments} == {technician.id}

        from app.models.invoice import InvoiceLineItem

        invoice = await db.get(Invoice, result.invoice_id)
        assert invoice is not None
        assert float(invoice.subtotal) == 400.0
        assert float(invoice.total) == 420.0
        line_count = len(
            (
                await db.execute(
                    select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id)
                )
            )
            .scalars()
            .all()
        )
        assert line_count == 2

        again = await svc.convert_quote(
            ws.id,
            quote.id,
            scheduled_start=start,
            scheduled_end=end,
            crew_id=crew.id,
            technician_ids=[technician.id],
        )
        assert again.job_id == result.job_id
        assert again.invoice_id == result.invoice_id
        assert again.idempotent_replay is True

        with pytest.raises(ConflictError, match="different handoff details"):
            await svc.convert_quote(
                ws.id,
                quote.id,
                scheduled_start=start + timedelta(days=1),
                scheduled_end=end + timedelta(days=1),
                crew_id=crew.id,
                technician_ids=[technician.id],
            )


async def test_convert_credits_paid_deposit_to_invoice() -> None:
    """A deposit already collected on the quote must not be billed twice.

    The client paid the deposit on the public proposal page, so the converted
    invoice has to open with that amount already credited and only the remaining
    balance outstanding.
    """
    from app.services.payments.quote_deposit_service import mark_deposit_paid

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)

        created = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Roof wash",
                deposit_percentage=25.0,
                line_items=[
                    QuoteLineItemCreate(name="Wash", quantity=1, unit_price=2000.0),
                ],
            ),
        )
        quote = await db.get(Quote, created.id)
        assert quote is not None
        await svc.approve_quote(ws.id, quote.id)
        # Client paid 25% of 2000 = 500 on the public proposal page.
        await mark_deposit_paid(db, quote, payment_intent_id="pi_deposit_test")

        result = await svc.convert_quote(ws.id, quote.id, create_job=False, create_invoice=True)
        assert result.invoice_id is not None

        invoice = await db.get(Invoice, result.invoice_id)
        assert invoice is not None
        assert float(invoice.total) == 2000.0
        # The 500 deposit is already collected -> only 1500 is still owed.
        assert float(invoice.amount_paid) == 500.0
        assert invoice.status == "partial"


async def test_unpaid_required_deposit_needs_confirmation_but_no_deposit_does_not() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Lighting",
                deposit_percentage=25,
                line_items=[QuoteLineItemCreate(name="Install", unit_price=1000)],
            ),
        )
        await svc.approve_quote(ws.id, quote.id)
        start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        end = start + timedelta(hours=2)
        with pytest.raises(ConflictError) as exc:
            await svc.convert_quote(
                ws.id,
                quote.id,
                create_invoice=False,
                scheduled_start=start,
                scheduled_end=end,
            )
        assert exc.value.code == "unpaid_deposit_confirmation_required"

        accepted = await svc.convert_quote(
            ws.id,
            quote.id,
            create_invoice=False,
            scheduled_start=start,
            scheduled_end=end,
            confirm_unpaid_deposit=True,
        )
        assert accepted.job_id is not None

        no_deposit = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="No deposit",
                line_items=[QuoteLineItemCreate(name="Install", unit_price=500)],
            ),
        )
        await svc.approve_quote(ws.id, no_deposit.id)
        no_deposit_result = await svc.convert_quote(
            ws.id,
            no_deposit.id,
            create_invoice=False,
            scheduled_start=start + timedelta(days=1),
            scheduled_end=end + timedelta(days=1),
        )
        assert no_deposit_result.job_id is not None


async def test_convert_schedules_job_when_window_supplied() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        location = await _make_location(db, ws.id, contact.id)
        svc = QuoteService(db)

        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                service_location_id=location.id,
                title="Install lighting",
                line_items=[QuoteLineItemCreate(name="Labor", unit_price=150.0)],
            ),
        )
        await svc.approve_quote(ws.id, quote.id)

        start = datetime(2026, 12, 1, 15, 0, tzinfo=UTC)
        end = start + timedelta(hours=3)
        result = await svc.convert_quote(
            ws.id,
            quote.id,
            create_invoice=False,
            scheduled_start=start,
            scheduled_end=end,
        )

        assert result.job_id is not None
        job = await db.get(Job, result.job_id)
        assert job is not None
        # The window is stored and the job lands on the calendar as scheduled.
        assert job.scheduled_start == start
        assert job.scheduled_end == end
        assert job.status == "scheduled"


async def test_convert_is_scoped_to_the_sales_representatives_quote() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _make_workspace(db)
        contact = await _make_contact(db, workspace.id)
        owner = await _make_member(db, workspace.id, name="Quote Owner")
        other_sales_rep = await _make_member(db, workspace.id, name="Other Sales Rep")
        service = QuoteService(db)
        quote = await service.create_quote(
            workspace.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Owned approved quote",
                line_items=[QuoteLineItemCreate(name="Labor", unit_price=500.0)],
            ),
            created_by_id=owner.id,
            assigned_user_id=owner.id,
        )
        await service.approve_quote(workspace.id, quote.id)
        start = datetime(2026, 12, 8, 15, 0, tzinfo=UTC)
        end = start + timedelta(hours=3)

        with pytest.raises(NotFoundError, match="Quote not found"):
            await service.convert_quote(
                workspace.id,
                quote.id,
                create_invoice=False,
                scheduled_start=start,
                scheduled_end=end,
                owner_user_id=other_sales_rep.id,
            )

        with pytest.raises(PermissionDeniedError, match="Billing access"):
            await service.convert_quote(
                workspace.id,
                quote.id,
                create_job=False,
                create_invoice=True,
                allow_invoice_creation=False,
                owner_user_id=owner.id,
            )

        stored_quote = await db.get(Quote, quote.id)
        assert stored_quote is not None
        assert stored_quote.converted_job_id is None
        assert stored_quote.converted_invoice_id is None
        result = await service.convert_quote(
            workspace.id,
            quote.id,
            create_invoice=False,
            scheduled_start=start,
            scheduled_end=end,
            owner_user_id=owner.id,
        )
        assert result.job_id is not None


async def test_convert_requires_approved_status() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        quote = await svc.create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                line_items=[QuoteLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )
        await svc.mark_sent(ws.id, quote.id)

        with pytest.raises(ConflictError):
            await svc.convert_quote(ws.id, quote.id)


async def _enable_lighting_pricing(db: AsyncSession, ws: Workspace) -> None:
    """Seed a workspace pricing config with both holiday services enabled.

    ``fee_buffer=0`` keeps totals exact so the asserted dollars are obvious.
    """
    pricing = PricingSettings(
        financing=FinancingConfig(enabled=True, fee_buffer=0.0),
        permanent=PermanentConfig(
            enabled=True, per_ft=30, controller_base=300, per_channel=0, minimum=0
        ),
        christmas=ChristmasConfig(enabled=True, roofline_per_ft=6, minimum=0),
    )
    ws.settings = {"pricing": pricing.model_dump(mode="json")}
    await db.flush()


async def test_create_quote_from_estimate_persists_priced_lines_and_contact() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        svc = QuoteService(db)

        quote = await svc.create_quote_from_estimate(
            ws.id,
            EstimateQuoteRequest(
                side="permanent",
                feet=100,
                client_name="Dana Rivers",
                client_phone="+15551230000",
                deposit_percentage=30,
            ),
        )

        # Default 100-ft kit COGS ($1,249) × Standard (3.0), with no fee buffer.
        assert quote.number == "QUO-000001"
        assert quote.status == "draft"
        assert quote.title == "Permanent Holiday Lighting"
        assert quote.total == 3747.0
        assert quote.deposit_percentage == 30
        assert quote.deposit_amount == 1124.1
        assert quote.deposit_required is True
        # Client details resolved onto a CRM contact (phone-keyed).
        assert quote.contact_id is not None
        assert [kit.model_dump() for kit in quote.selected_permanent_kits] == [
            {"feet": 100, "quantity": 1}
        ]
        names = [li.name for li in quote.line_items]
        assert "Permanent lighting package" in names
        # The persisted line items sum back to the quote total.
        assert round(sum(li.total for li in quote.line_items), 2) == quote.total

        listed = await svc.list_quotes(ws.id)
        assert [kit.model_dump() for kit in listed.items[0].selected_permanent_kits] == [
            {"feet": 100, "quantity": 1}
        ]


async def test_create_quote_from_estimate_links_workspace_project_and_contact() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        contact = await _make_contact(db, ws.id)
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Pat permanent roofline",
            document={
                "version": 2,
                "projectType": "permanent",
                "activeShotId": None,
                "shots": [],
                "updatedAt": "2026-08-26T12:00:00Z",
            },
        )
        db.add(project)
        await db.flush()

        quote = await QuoteService(db).create_quote_from_estimate(
            ws.id,
            EstimateQuoteRequest(
                side="permanent",
                feet=100,
                lighting_project_id=project.id,
            ),
        )

        assert quote.contact_id == contact.id
        assert quote.lighting_project_id == project.id
        assert quote.proposal_document is None


async def test_create_quote_from_estimate_snapshots_preview_and_installation_shot() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        contact = await _make_contact(db, ws.id)
        manager = await _make_member(db, ws.id, name="Office Manager")
        membership = await db.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws.id,
                WorkspaceMembership.user_id == manager.id,
            )
        )
        assert membership is not None
        membership.role = "manager"
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Pat permanent roofline",
            document=_permanent_project_document(),
        )
        db.add(project)
        await db.flush()

        svc = QuoteService(db)
        quote = await svc.create_quote_from_estimate(
            ws.id,
            EstimateQuoteRequest(
                side="permanent",
                feet=100,
                lighting_project_id=project.id,
                proposal_preview={
                    "shot_id": "front",
                    "image": "data:image/jpeg;base64,/9j/2Q==",
                },
            ),
        )

        assert quote.contact_id == contact.id
        assert quote.lighting_project_id == project.id
        assert quote.proposal_document is not None
        assert quote.proposal_document["service"] == "permanent"
        assert quote.proposal_document["mockups"] == [
            {
                "image": "data:image/jpeg;base64,/9j/2Q==",
                "caption": "Pat permanent roofline proposed permanent lighting",
            }
        ]
        await db.refresh(project)
        assert project.installation_shot_id == "front"

        sent = await svc.mark_sent(ws.id, quote.id)
        assert sent.public_token
        public = await svc.get_public_proposal(sent.public_token)
        assert public.proposal_document is not None
        assert public.proposal_document["mockups"] == quote.proposal_document["mockups"]

        # The homeowner never sees how many feet we measured. This asserts the
        # payload their browser actually fetches, not just the label helper, so a
        # measurement reintroduced anywhere upstream fails here.
        assert public.line_items
        leaked = [
            text
            for li in public.line_items
            for text in (li.name, li.description)
            if text and re.search(r"\d\s*(ft|feet|linear)", text, re.IGNORECASE)
        ]
        assert leaked == []

        # Default: one firm number, exactly as before the range option existed.
        assert public.price_range is None

        await svc.approve_quote(ws.id, quote.id)
        scheduled_start = datetime(2026, 9, 4, 13, tzinfo=UTC)
        converted = await svc.convert_quote(
            ws.id,
            quote.id,
            create_invoice=False,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_start + timedelta(hours=2),
        )
        assert converted.job_id is not None
        job = await db.get(Job, converted.job_id)
        assert job is not None
        assert job.contact_id == contact.id
        assert job.source_quote_id == quote.id
        assert job.lighting_project_id == project.id

        installation_plan = await JobService(db).get_installation_plan(
            job.id,
            ws.id,
            membership=membership,
            user_id=manager.id,
        )
        assert installation_plan.project_id == project.id
        assert installation_plan.proposal_preview_image == "data:image/jpeg;base64,/9j/2Q=="
        assert installation_plan.design.items[0].product_id == "product-1"


async def test_create_quote_from_estimate_can_send_a_price_range(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        contact = await _make_contact(db, ws.id, email="pat@example.com")
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Pat permanent roofline",
            document=_permanent_project_document(),
        )
        db.add(project)
        await db.flush()

        svc = QuoteService(db)
        preview = {
            "shot_id": "front",
            "image": "data:image/jpeg;base64,/9j/2Q==",
        }
        # The browser may choose the top, but the server owns the bottom. It
        # refuses a range that does not contain the exact quote total.
        with pytest.raises(ValidationError, match="Higher range amount must be greater"):
            await svc.create_quote_from_estimate(
                ws.id,
                EstimateQuoteRequest(
                    side="permanent",
                    feet=100,
                    client_email="pat@example.com",
                    price_range_high=1,
                    lighting_project_id=project.id,
                    proposal_preview=preview,
                ),
            )

        quote = await svc.create_quote_from_estimate(
            ws.id,
            EstimateQuoteRequest(
                side="permanent",
                feet=100,
                client_email="pat@example.com",
                price_range_high=4000,
                lighting_project_id=project.id,
                proposal_preview=preview,
            ),
        )
        assert quote.proposal_document is not None
        assert quote.proposal_document["price_range_high"] == 4000

        delivered_prices: list[tuple[str, str]] = []

        async def capture_email(**kwargs: object) -> bool:
            delivered_prices.append((str(kwargs["amount_label"]), str(kwargs["amount_str"])))
            return True

        from app.services import email as email_module

        monkeypatch.setattr(email_module, "send_quote_email", capture_email)
        sent = await svc.mark_sent(ws.id, quote.id)
        assert delivered_prices == [("Estimated range", f"{float(quote.total):.2f}–4000.00 USD")]
        public = await svc.get_public_proposal(sent.public_token)
        assert public.price_range is not None
        # The quoted total is the bottom of the range, so approving it and the
        # deposit charged still resolve to the exact money on the quote.
        assert public.price_range.low == public.total == float(quote.total)
        assert public.price_range.high == 4000
        # The staff-entered top is exposed only through the validated public pair.
        assert "price_range_high" not in (public.proposal_document or {})


async def test_price_range_is_rejected_without_a_permanent_proposal_preview() -> None:
    # The range rides on the proposal snapshot; accepting the top without one
    # would silently send the firm price the rep chose not to commit to.
    with pytest.raises(PydanticValidationError):
        EstimateQuoteRequest(side="permanent", feet=100, price_range_high=4000)
    with pytest.raises(PydanticValidationError):
        EstimateQuoteRequest(side="seasonal", feet=100, price_range_high=4000)


async def test_create_quote_from_estimate_rejects_preview_for_missing_project_shot() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        contact = await _make_contact(db, ws.id)
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Pat permanent roofline",
            document=_permanent_project_document(),
        )
        db.add(project)
        await db.flush()

        with pytest.raises(ValidationError, match="shot is missing"):
            await QuoteService(db).create_quote_from_estimate(
                ws.id,
                EstimateQuoteRequest(
                    side="permanent",
                    feet=100,
                    lighting_project_id=project.id,
                    proposal_preview={
                        "shot_id": "other",
                        "image": "data:image/jpeg;base64,/9j/2Q==",
                    },
                ),
            )

        await db.refresh(project)
        assert project.installation_shot_id is None
        stored_quote = await db.scalar(select(Quote).where(Quote.workspace_id == ws.id))
        assert stored_quote is None


async def test_create_quote_from_estimate_rejects_preview_for_an_undesigned_shot() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        contact = await _make_contact(db, ws.id)
        document = _permanent_project_document()
        shots = document["shots"]
        assert isinstance(shots, list)
        shots.append(
            {
                "id": "blank-side",
                "photo": {
                    "dataUrl": "data:image/png;base64,AAAA",
                    "width": 1200,
                    "height": 800,
                },
                "design": {"runs": [], "items": [], "planImages": [], "calibration": None},
                "dusk": 0.4,
            }
        )
        project = LightingProject(
            workspace_id=ws.id,
            contact_id=contact.id,
            name="Pat permanent roofline",
            document=document,
        )
        db.add(project)
        await db.flush()

        with pytest.raises(ValidationError, match="shot has no saved lighting design"):
            await QuoteService(db).create_quote_from_estimate(
                ws.id,
                EstimateQuoteRequest(
                    side="permanent",
                    feet=100,
                    lighting_project_id=project.id,
                    proposal_preview={
                        "shot_id": "blank-side",
                        "image": "data:image/jpeg;base64,/9j/2Q==",
                    },
                ),
            )

        await db.refresh(project)
        assert project.installation_shot_id is None
        stored_quote = await db.scalar(select(Quote).where(Quote.workspace_id == ws.id))
        assert stored_quote is None


async def test_create_quote_from_estimate_rejects_other_workspace_project() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other_ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        other_contact = await _make_contact(db, other_ws.id)
        project = LightingProject(
            workspace_id=other_ws.id,
            contact_id=other_contact.id,
            name="Other tenant project",
            document={
                "version": 2,
                "projectType": "permanent",
                "activeShotId": None,
                "shots": [],
                "updatedAt": "2026-08-26T12:00:00Z",
            },
        )
        db.add(project)
        await db.flush()

        with pytest.raises(HTTPException, match="Lighting project not found") as exc_info:
            await QuoteService(db).create_quote_from_estimate(
                ws.id,
                EstimateQuoteRequest(
                    side="permanent",
                    feet=100,
                    lighting_project_id=project.id,
                ),
            )
        assert exc_info.value.status_code == 404


async def test_create_quote_from_complex_estimate_persists_overall_discount() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        svc = QuoteService(db)

        quote = await svc.create_quote_from_estimate(
            ws.id,
            EstimateQuoteRequest(
                side="permanent",
                proposal_side="permanent",
                feet=100,
                permanent_complexity="complex",
                permanent_complexity_feet={"complex": 100},
                discount_amount=500,
            ),
        )

        assert quote.subtotal == 4371.5
        assert quote.discount_amount == 500
        assert quote.total == 3871.5
        assert round(sum(line.total for line in quote.line_items), 2) == quote.subtotal


async def test_create_quote_from_estimate_rejects_discount_above_total() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        svc = QuoteService(db)

        with pytest.raises(ValidationError, match="Discount cannot exceed"):
            await svc.create_quote_from_estimate(
                ws.id,
                EstimateQuoteRequest(
                    side="seasonal",
                    proposal_side="seasonal",
                    feet=100,
                    discount_amount=601,
                ),
            )


async def test_create_quote_from_estimate_seasonal_itemizes_decor() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        svc = QuoteService(db)

        quote = await svc.create_quote_from_estimate(
            ws.id,
            EstimateQuoteRequest(
                side="seasonal",
                feet=100,
                christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
            ),
        )

        # roofline 600 + trees 520 + garland 400 = 1520.
        assert quote.title == "Christmas Lighting"
        assert quote.total == 1520.0
        assert quote.contact_id is None  # no client details supplied -> unlinked
        assert quote.selected_permanent_kits == []
        names = [li.name for li in quote.line_items]
        assert "Roofline" in names


async def test_create_quote_from_estimate_empty_design_is_rejected() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        await _enable_lighting_pricing(db, ws)
        svc = QuoteService(db)

        # No feet and no decor -> nothing to quote; the rep gets an actionable error.
        with pytest.raises(ValidationError):
            await svc.create_quote_from_estimate(
                ws.id, EstimateQuoteRequest(side="seasonal", feet=0)
            )


# --------------------------------------------------------------------------- #
# Price-validity window (pricing.quote_validity_days)
# --------------------------------------------------------------------------- #
async def _orm_quote(db: AsyncSession, quote_id: uuid.UUID) -> Quote:
    """Reload the ORM row: ``create_quote`` returns a response schema."""
    result = await db.execute(select(Quote).where(Quote.id == quote_id))
    return result.scalar_one()


async def test_send_stamps_the_default_thirty_day_validity_window() -> None:
    """A sent quote stops being open-ended, so a stale price cannot be accepted."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)
        assert created.expiry_date is None  # drafts carry no deadline

        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)

        # Asserted against the quote's own ``sent_at`` rather than a local
        # ``date.today()``: the window is anchored to the stored UTC send stamp,
        # so a hardcoded local date makes this test fail after 5pm Pacific.
        assert quote.sent_at is not None
        assert quote.expiry_date == quote.sent_at.date() + timedelta(days=30)


async def test_validity_window_is_per_workspace_configurable() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        ws.settings = {"pricing": {"quote_validity_days": 14}}
        await db.flush()
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)

        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)

        assert quote.sent_at is not None
        assert quote.expiry_date == quote.sent_at.date() + timedelta(days=14)


async def test_operator_set_expiry_is_never_overwritten() -> None:
    """An explicit deadline is a commitment; the default only fills a blank."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        explicit = date.today() + timedelta(days=90)
        created = await svc.create_quote(
            ws.id, QuoteCreate(line_items=[], expiry_date=explicit), created_by_id=None
        )

        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)

        assert quote.expiry_date == explicit


async def test_resending_never_extends_a_deadline_already_shown() -> None:
    """Re-sending the same link must not quietly move the date the customer saw."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)

        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)
        first_expiry = quote.expiry_date
        # Simulate the quote having been sent a week ago and re-sent today.
        quote.sent_at = datetime.now(UTC) - timedelta(days=7)
        await svc._ensure_sent_state(quote)

        assert quote.expiry_date == first_expiry


async def test_expiry_can_be_switched_off_for_a_workspace() -> None:
    """A workspace that never wants quotes to lapse leaves the date blank."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        ws.settings = {"pricing": {"quote_expiry_enabled": False}}
        await db.flush()
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)

        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)

        assert quote.sent_at is not None
        # No deadline at all, rather than a very distant one: a blank expiry is
        # what ``overdue_sent_predicate`` treats as never lapsing.
        assert quote.expiry_date is None

        await svc._expire_overdue(ws.id)
        await db.refresh(quote)
        assert quote.status == "sent"


async def test_reopening_a_lapsed_quote_survives_the_expiry_sweep() -> None:
    """The whole point: it must not be re-expired by the next read."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)
        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)
        # Lapse it the way real time would.
        quote.expiry_date = date.today() - timedelta(days=1)
        await db.flush()
        await svc._expire_overdue(ws.id)
        await db.refresh(quote)
        assert quote.status == "expired"

        reopened = await svc.reopen_quote(ws.id, created.id)

        assert reopened.status == "sent"
        # A fresh window, not the stale date: leaving the past date in place
        # would let the very next sweep re-expire it.
        assert reopened.expiry_date == date.today() + timedelta(days=30)

        await svc._expire_overdue(ws.id)
        await db.refresh(quote)
        assert quote.status == "sent"


async def test_reopening_with_expiry_switched_off_clears_the_deadline() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)
        quote = await _orm_quote(db, created.id)
        await svc._ensure_sent_state(quote)
        quote.expiry_date = date.today() - timedelta(days=1)
        await db.flush()
        await svc._expire_overdue(ws.id)
        await db.refresh(quote)
        assert quote.status == "expired"

        ws.settings = {"pricing": {"quote_expiry_enabled": False}}
        await db.flush()
        reopened = await svc.reopen_quote(ws.id, created.id)

        assert reopened.status == "sent"
        assert reopened.expiry_date is None


@pytest.mark.parametrize("status", ["draft", "sent", "approved", "declined"])
async def test_only_an_expired_quote_can_be_reopened(status: str) -> None:
    """Approved and declined are customer decisions; reopen must not undo them."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = QuoteService(db)
        created = await svc.create_quote(ws.id, QuoteCreate(line_items=[]), created_by_id=None)
        quote = await _orm_quote(db, created.id)
        quote.status = status
        await db.flush()

        with pytest.raises(ConflictError):
            await svc.reopen_quote(ws.id, created.id)

        await db.refresh(quote)
        assert quote.status == status


async def test_reopen_cannot_reach_another_workspaces_quote() -> None:
    async with AsyncSessionLocal() as db:
        owner = await _make_workspace(db)
        intruder = await _make_workspace(db)
        svc = QuoteService(db)
        created = await svc.create_quote(owner.id, QuoteCreate(line_items=[]), created_by_id=None)
        quote = await _orm_quote(db, created.id)
        quote.status = "expired"
        quote.expiry_date = date.today() - timedelta(days=1)
        await db.flush()

        with pytest.raises(HTTPException) as excinfo:
            await svc.reopen_quote(intruder.id, created.id)
        assert excinfo.value.status_code == 404

        await db.refresh(quote)
        assert quote.status == "expired"
