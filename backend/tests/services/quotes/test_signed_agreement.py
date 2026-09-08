"""Real-DB tests for the signed agreement document.

Covers the guarantees that make the document usable as evidence: it is produced
on a signed approval, the stored bytes are a real non-empty PDF, the recorded
hash matches those exact bytes, a second approval does not overwrite the
original, listing never drags the blob out of Postgres, and neither the public
proposal payload nor any public route exposes the document or the signer's IP.

Marked ``integration`` and deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.db.tenancy import scope_session_to_workspace
from app.models.contact import Contact
from app.models.quote import Quote
from app.models.signed_agreement_document import (
    AGREEMENT_METADATA_COLUMNS,
    SignedAgreementDocument,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.quotes import QuoteService
from app.services.quotes.signature import SignatureCeremony

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

SIGNER_IP = "203.0.113.77"


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _no_outbound_email() -> AsyncIterator[None]:
    """Keep the suite from touching Resend while still exercising the send path."""
    with (
        patch("app.services.quotes.quote_service.send_quote_acceptance_receipt", AsyncMock()),
        patch("app.services.quotes.agreement_document.send_event_notification_email", AsyncMock()),
    ):
        yield


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        slug=f"sig-{uuid.uuid4().hex[:8]}",
        settings={
            "timezone": "America/Detroit",
            "proposal_template": {
                "business_name": "Maxteriors Lighting Co.",
                "default_terms": "Cancel within 3 business days for a full refund.",
            },
        },
    )
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(db: AsyncSession, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    email = f"signer-{uuid.uuid4().hex[:8]}@example.com"
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


async def _sent_quote(svc: QuoteService, workspace_id: uuid.UUID, contact_id: int) -> str:
    created = await svc.create_quote(
        workspace_id,
        QuoteCreate(
            contact_id=contact_id,
            title="Backyard lighting install",
            terms="Cancel within 3 business days for a full refund.",
            line_items=[QuoteLineItemCreate(name="Fixtures", quantity=6, unit_price=120.0)],
        ),
    )
    sent = await svc.mark_sent(workspace_id, created.id)
    assert sent.public_token is not None
    return sent.public_token


def _ceremony(name: str = "Dana Homeowner") -> SignatureCeremony:
    return SignatureCeremony(
        signed_name=name,
        econsent_accepted=True,
        cancellation_acknowledged=True,
        ip_address=SIGNER_IP,
    )


async def _sign(db: AsyncSession, token: str, ceremony: SignatureCeremony | None = None) -> None:
    await QuoteService(db).approve_public(
        token, proposal_version=None, signature=ceremony or _ceremony()
    )


async def _document_for(db: AsyncSession, token: str) -> SignedAgreementDocument:
    quote = (await db.execute(select(Quote).where(Quote.public_token == token))).scalar_one()
    return (
        await db.execute(
            select(SignedAgreementDocument).where(SignedAgreementDocument.quote_id == quote.id)
        )
    ).scalar_one()


async def test_signed_approval_stores_a_real_pdf_whose_hash_matches_the_bytes() -> None:
    """The core guarantee: bytes exist, are a PDF, and sha256 certifies them."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)
        await _sign(db, token)

        document = await _document_for(db, token)
        assert document.data, "agreement bytes must be stored, not re-rendered on demand"
        assert document.data[:5] == b"%PDF-", "stored bytes must be a real PDF"
        assert document.byte_size == len(document.data)
        assert document.sha256 == hashlib.sha256(document.data).hexdigest()
        assert document.content_type == "application/pdf"
        assert document.terms_version == 1
        assert document.workspace_id == ws.id


async def test_second_approval_does_not_overwrite_the_original_document() -> None:
    """Re-approving must keep the exact bytes the customer was sent."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)

        await _sign(db, token)
        original = await _document_for(db, token)
        original_id, original_sha = original.id, original.sha256
        original_generated_at = original.generated_at

        # A different name on the retry would rewrite the signature block if the
        # guard were missing, making the change visible in the stored bytes.
        await _sign(db, token, _ceremony(name="Someone Else"))

        rows = (
            (
                await db.execute(
                    select(SignedAgreementDocument).where(
                        SignedAgreementDocument.quote_id == original.quote_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, "regeneration must be refused, not duplicated"
        assert rows[0].id == original_id
        assert rows[0].sha256 == original_sha
        assert rows[0].generated_at == original_generated_at


async def test_direct_regeneration_is_refused_and_returns_the_original() -> None:
    """The service-level guard, exercised directly.

    The re-approval path above never reaches generation (an already-approved
    quote short-circuits earlier), so it cannot prove this. A retry worker, an
    operator-triggered resend, or a second racing request all call this function
    directly against a quote that already has a document -- that is the case the
    "generate once" rule actually has to survive.
    """
    from app.services.quotes.agreement_document import generate_signed_agreement

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)
        await _sign(db, token)

        original = await _document_for(db, token)
        quote = await db.get(Quote, original.quote_id)
        assert quote is not None

        again = await generate_signed_agreement(db, quote)
        assert again is not None
        assert again.id == original.id, "must return the original, not a fresh render"
        assert again.sha256 == original.sha256
        assert again.generated_at == original.generated_at

        rows = (
            (
                await db.execute(
                    select(SignedAgreementDocument).where(
                        SignedAgreementDocument.quote_id == quote.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_re_signing_does_not_move_the_recorded_moment_of_consent() -> None:
    """The signature itself is frozen, not just the PDF."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)

        await _sign(db, token)
        quote = (await db.execute(select(Quote).where(Quote.public_token == token))).scalar_one()
        first_signed_at, first_name = quote.signed_at, quote.signed_name

        await _sign(db, token, _ceremony(name="Someone Else"))
        await db.refresh(quote)
        assert quote.signed_at == first_signed_at
        assert quote.signed_name == first_name


async def test_partial_ceremony_is_refused_rather_than_half_recorded() -> None:
    """A typed name without both affirmations is not a signature."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)

        await _sign(
            db,
            token,
            SignatureCeremony(
                signed_name="Dana Homeowner",
                econsent_accepted=True,
                cancellation_acknowledged=False,  # never ticked
                ip_address=SIGNER_IP,
            ),
        )

        quote = (await db.execute(select(Quote).where(Quote.public_token == token))).scalar_one()
        assert quote.status == "approved", "the approval itself must still succeed"
        assert quote.signed_at is None
        assert quote.signed_name is None
        assert quote.signed_ip is None
        # No signature means no agreement to certify.
        assert (
            await db.scalar(
                select(SignedAgreementDocument).where(SignedAgreementDocument.quote_id == quote.id)
            )
        ) is None


async def test_unsigned_legacy_approval_produces_no_document() -> None:
    """One-click acceptance (no ceremony) must not fabricate an agreement."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)

        await QuoteService(db).approve_public(token, proposal_version=None, signature=None)

        quote = (await db.execute(select(Quote).where(Quote.public_token == token))).scalar_one()
        assert quote.status == "approved"
        assert (
            await db.scalar(
                select(SignedAgreementDocument).where(SignedAgreementDocument.quote_id == quote.id)
            )
        ) is None


async def test_render_failure_does_not_roll_back_the_approval() -> None:
    """A lost PDF is recoverable; a lost signature is not."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)

        with patch(
            "app.services.quotes.agreement_document.render_pdf",
            side_effect=RuntimeError("pango exploded"),
        ):
            await _sign(db, token)

        quote = (await db.execute(select(Quote).where(Quote.public_token == token))).scalar_one()
        assert quote.status == "approved", "approval must commit despite a render failure"
        assert quote.signed_at is not None, "the signature must survive"
        assert quote.signed_name == "Dana Homeowner"
        assert (
            await db.scalar(
                select(SignedAgreementDocument).where(SignedAgreementDocument.quote_id == quote.id)
            )
        ) is None

        # Retryable: a later call produces the document from the frozen row.
        from app.services.quotes.agreement_document import ensure_signed_agreement

        recovered = await ensure_signed_agreement(db, quote)
        assert recovered is not None
        assert recovered.data[:5] == b"%PDF-"


async def test_list_query_does_not_load_the_data_column() -> None:
    """A list view must never pull megabytes of BYTEA out of Postgres."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)
        await _sign(db, token)
        db.expunge_all()

        rows = (
            (
                await db.execute(
                    select(SignedAgreementDocument)
                    .options(load_only(*AGREEMENT_METADATA_COLUMNS, raiseload=True))
                    .where(SignedAgreementDocument.workspace_id == ws.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].byte_size > 0  # metadata is present
        # `data` was deferred with raiseload, so touching it raises rather than
        # silently emitting a second query that loads the blob.
        with pytest.raises(Exception, match="raiseload|not available|deferred"):
            _ = rows[0].data


async def test_quote_detail_exposes_agreement_metadata_but_never_the_ip() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token = await _sent_quote(svc, ws.id, contact.id)
        await _sign(db, token)

        quote = (await db.execute(select(Quote).where(Quote.public_token == token))).scalar_one()
        detail = await svc.get_quote(ws.id, quote.id)

        assert detail.signed_agreement is not None
        assert detail.signed_agreement.byte_size > 0
        assert detail.signed_agreement.generated_at is not None
        assert SIGNER_IP not in detail.model_dump_json()


async def test_public_proposal_payload_never_exposes_the_document_or_the_ip() -> None:
    """The customer's own token must not reach the evidence or the IP."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = QuoteService(db)
        token = await _sent_quote(svc, ws.id, contact.id)
        await _sign(db, token)

        payload = (await svc.get_public_proposal(token)).model_dump_json()
        assert SIGNER_IP not in payload
        assert "signed_ip" not in payload
        assert "signed_agreement" not in payload
        assert "%PDF" not in payload


async def test_duplicate_document_insert_is_refused_by_the_database() -> None:
    """The one-per-quote rule survives a race, not just the service guard."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)
        await _sign(db, token)
        document = await _document_for(db, token)

        db.add(
            SignedAgreementDocument(
                workspace_id=ws.id,
                quote_id=document.quote_id,
                filename="forged.pdf",
                content_type="application/pdf",
                byte_size=4,
                data=b"fake",
                sha256="0" * 64,
                terms_version=1,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


async def test_another_workspace_cannot_read_the_agreement() -> None:
    """Cross-tenant isolation, through the real session-level tenant filter.

    Uses ``scope_session_to_workspace`` exactly as ``app/api/deps.py`` does on
    every authenticated request, so this exercises the filter that actually runs
    in production rather than a hand-written ``WHERE workspace_id =`` clause.
    """
    async with AsyncSessionLocal() as setup:
        ws = await _make_workspace(setup)
        other = await _make_workspace(setup)
        contact = await _make_contact(setup, ws.id)
        token = await _sent_quote(QuoteService(setup), ws.id, contact.id)
        await _sign(setup, token)
        owner_id, intruder_id = ws.id, other.id

    async with AsyncSessionLocal() as scoped:
        scope_session_to_workspace(scoped, intruder_id)
        visible = (await scoped.execute(select(SignedAgreementDocument))).scalars().all()
        assert visible == [], "a neighbouring workspace must not see the agreement"

    async with AsyncSessionLocal() as scoped:
        scope_session_to_workspace(scoped, owner_id)
        mine = (await scoped.execute(select(SignedAgreementDocument))).scalars().all()
        assert len(mine) == 1, "the owning workspace still sees its own agreement"


async def test_download_endpoint_is_absent_from_every_public_router() -> None:
    """The document must not be reachable by the customer's proposal token.

    The public routers are token-keyed and unauthenticated; the agreement holds
    the signer's IP and the completion certificate, so it belongs only on the
    authenticated router. Asserted structurally because a future route added to
    the wrong router would be invisible to a request-level test that only probes
    the paths we already know about.
    """
    from app.api.v1.quotes import comparison_public_router, public_router, router

    # getattr, not route.path: Starlette's BaseRoute does not declare `path`
    # (only its Route subclasses do), so this stays type-clean without an ignore.
    public_paths = [
        getattr(route, "path", "")
        for route in (*public_router.routes, *comparison_public_router.routes)
    ]
    assert not any("signed-agreement" in path for path in public_paths)

    authed_paths = [getattr(route, "path", "") for route in router.routes]
    assert any("signed-agreement" in path for path in authed_paths), (
        "the download route must exist on the authenticated router"
    )


async def test_download_endpoint_refuses_a_quote_from_another_workspace() -> None:
    """Workspace scoping on the endpoint's own dependency, not just the query."""
    from app.api.v1.quotes import _scoped_quote

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)
        await _sign(db, token)
        document = await _document_for(db, token)

        user = User(
            email=f"op-{uuid.uuid4().hex[:8]}@example.com",
            full_name="Operator",
            hashed_password="not-used",
        )
        db.add(user)
        await db.flush()
        membership = WorkspaceMembership(workspace_id=other.id, user_id=user.id, role="owner")
        db.add(membership)
        await db.flush()

        # An owner of a *different* workspace resolving the signed quote: the
        # shared dependency the download route depends on must refuse it.
        with pytest.raises(HTTPException) as exc:
            await _scoped_quote(other.id, document.quote_id, user, membership, db)
        assert exc.value.status_code == 404


async def test_document_contains_the_certificate_facts() -> None:
    """The parts that settle a dispute must actually be in the file."""
    import io

    from pypdf import PdfReader

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        token = await _sent_quote(QuoteService(db), ws.id, contact.id)
        await _sign(db, token)
        document = await _document_for(db, token)

        text = "\n".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(document.data)).pages
        )
        assert "Dana Homeowner" in text, "typed name must appear"
        assert SIGNER_IP in text, "signer IP belongs in the retained evidence copy"
        assert "Cancel within 3 business days" in text, "cancellation terms verbatim"
        assert "Completion certificate" in text
        assert "E-SIGN Act" in text and "UETA" in text, "per-page legal footer"
        assert "EST" in text or "EDT" in text, "timestamps render in the workspace timezone"
        # Detail labels render uppercase (CSS text-transform, which WeasyPrint bakes
        # into the extracted text), so match case-insensitively.
        assert "fixtures" in text.lower(), "the accepted line items must be in the contract"

        pages = [page.extract_text() or "" for page in PdfReader(io.BytesIO(document.data)).pages]
        # The footer is a CSS margin box, so it repeats per page rather than
        # appearing once at the end of the body.
        assert all("E-SIGN Act" in page for page in pages), "footer on EVERY page"
        # A page break between a field name and its value reads as a missing
        # field. Each label must sit on the same page as the value under it.
        for label in ("VIEW COUNT", "IP ADDRESS", "TERMS VERSION", "E-CONSENT ACCEPTED AT"):
            holding = [page for page in pages if label in page]
            assert holding, f"{label} missing from the certificate"
            after = holding[0].split(label, 1)[1].strip()
            assert after, f"{label} was orphaned at a page break, its value is on the next page"
