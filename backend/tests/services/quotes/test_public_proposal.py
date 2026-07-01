"""Real-DB integration tests for the public client-proposal surface.

Exercises the no-auth, token-keyed proposal flow end-to-end against Postgres: a
sent quote resolves to a safe payload, drafts/unknown tokens 404, approve flips
status and is idempotent, and an expired or declined proposal is rejected. Also
asserts (DB-free) that the public payload leaks no internal ids/costs. Marked
``integration`` and deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.schemas.proposal import PublicProposal, PublicProposalLineItem
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.exceptions import ConflictError, NotFoundError
from app.services.quotes import QuoteService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession, *, settings: dict | None = None) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        slug=f"quo-{uuid.uuid4().hex[:8]}",
        settings=settings or {},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    email = f"client-{uuid.uuid4().hex[:8]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Dana",
        last_name="Homeowner",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _sent_quote(
    svc: QuoteService,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    expiry: date | None = None,
) -> tuple[str, uuid.UUID]:
    created = await svc.create_quote(
        workspace_id,
        QuoteCreate(
            contact_id=contact_id,
            title="Backyard lighting install",
            expiry_date=expiry,
            line_items=[
                QuoteLineItemCreate(name="Fixtures", quantity=6, unit_price=120.0),
                QuoteLineItemCreate(name="Labor", quantity=1, unit_price=400.0, discount=50.0),
            ],
        ),
    )
    sent = await svc.mark_sent(workspace_id, created.id)
    assert sent.public_token is not None
    return sent.public_token, created.id


async def test_public_get_returns_safe_proposal_with_branding() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(
            db,
            settings={
                "proposal_template": {
                    "business_name": "Maxteriors Lighting Co.",
                    "brand_color": "#0A7C3A",
                    "intro": "Thanks for the opportunity to light up your yard.",
                    "default_terms": "50% deposit due on approval.",
                    "footer": "Licensed & insured — CA #123456",
                }
            },
        )
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote(svc, ws.id, contact.id)

        proposal = await svc.get_public_proposal(token)
        assert isinstance(proposal, PublicProposal)
        assert proposal.number.startswith("QUO-")
        assert proposal.status == "sent"
        # subtotal = 6*120 + (400 - 50) = 1070
        assert proposal.subtotal == 1070.0
        assert proposal.total == 1070.0
        assert len(proposal.line_items) == 2
        assert proposal.client_name == "Dana Homeowner"
        assert proposal.intro == "Thanks for the opportunity to light up your yard."
        assert proposal.terms == "50% deposit due on approval."
        assert proposal.branding.business_name == "Maxteriors Lighting Co."
        assert proposal.branding.brand_color == "#0A7C3A"
        assert proposal.branding.footer == "Licensed & insured — CA #123456"
        assert proposal.is_decided is False


async def test_unknown_and_draft_tokens_404() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)

        # Unknown token.
        with pytest.raises(NotFoundError):
            await svc.get_public_proposal("does-not-exist")

        # A draft has no token and must never resolve. Craft a fake token and
        # confirm the draft (still tokenless) is unreachable.
        await svc.create_quote(ws.id, QuoteCreate(contact_id=contact.id, line_items=[]))
        with pytest.raises(NotFoundError):
            await svc.get_public_proposal("draft-quote-has-no-token")


async def test_public_approve_flips_status_and_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote(svc, ws.id, contact.id)

        first = await svc.approve_public(token)
        assert first.status == "approved"

        # Idempotent: approving again stays approved (client double-clicks).
        second = await svc.approve_public(token)
        assert second.status == "approved"

        proposal = await svc.get_public_proposal(token)
        assert proposal.status == "approved"
        assert proposal.is_decided is True


async def test_public_decline_records_reason() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote(svc, ws.id, contact.id)

        result = await svc.decline_public(token, reason="Went with another vendor")
        assert result.status == "declined"

        # A declined proposal cannot then be approved by the client.
        with pytest.raises(ConflictError):
            await svc.approve_public(token)


async def test_expired_proposal_is_rejected() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token, _ = await _sent_quote(
            svc, ws.id, contact.id, expiry=date.today() - timedelta(days=1)
        )

        # Reading a lapsed proposal reflects the expired status truthfully.
        proposal = await svc.get_public_proposal(token)
        assert proposal.status == "expired"
        assert proposal.is_expired is True

        # And the client can no longer approve it.
        with pytest.raises(ConflictError):
            await svc.approve_public(token)


async def test_public_payload_leaks_no_internal_ids_or_costs() -> None:
    """Structural guard: the public schemas expose only proposal-safe fields."""
    leaked = {
        "id",
        "workspace_id",
        "contact_id",
        "created_by_id",
        "converted_job_id",
        "converted_invoice_id",
        "opportunity_id",
        "service_location_id",
        "cost",
        "margin",
    }
    assert leaked.isdisjoint(PublicProposal.model_fields)
    assert leaked.isdisjoint(PublicProposalLineItem.model_fields)
