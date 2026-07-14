"""Quote (estimate) business logic.

Mirrors :class:`app.services.invoices.invoice_service.InvoiceService`
conventions (``get_or_404``/``get_nested_or_404`` lookups, ``paginate`` for
lists, ``selectinload`` + explicit ``refresh`` so async serialization never
triggers a lazy load, ``float`` money math rounded to two decimals).

A quote's lifecycle is operator-driven: ``draft -> sent -> approved/declined``.
``expired`` is derived from ``expiry_date`` on a still-``sent`` quote and is
applied lazily (a scoped bulk UPDATE) on read so listed/fetched quotes are
truthful without a background job. An ``approved`` quote can be **converted**
into a scheduled :class:`Job` and/or an :class:`Invoice`; the resulting ids are
recorded on the quote so the sales -> work -> billing chain stays auditable.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.db.pagination import paginate
from app.models.catalog import CatalogItem
from app.models.quote import Quote, QuoteLineItem, generate_quote_token
from app.models.roofline_comparison import RooflineComparison
from app.models.workspace import Workspace
from app.schemas.estimate import (
    ChristmasEstimate,
    ComparisonShareRequest,
    ComparisonShareResult,
    LinearFeetEstimateRequest,
    LinearFeetEstimateResult,
    PermanentEstimate,
    PublicChristmasComparison,
    PublicComparison,
    PublicPermanentComparison,
)
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.schemas.pricing import PricingSettings
from app.schemas.proposal import (
    PublicProposal,
    PublicProposalActionResult,
    PublicProposalBranding,
    PublicProposalLineItem,
)
from app.schemas.proposal_wizard import ProposalDocument, ProposalWizardPayload
from app.schemas.quote import (
    PaginatedQuotes,
    QuoteConvertResponse,
    QuoteCreate,
    QuoteDeliverResult,
    QuoteDetailResponse,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteResponse,
    QuoteUpdate,
)
from app.services.automations.events import (
    EVENT_QUOTE_APPROVED,
    EVENT_QUOTE_CONVERTED,
    EVENT_QUOTE_DECLINED,
    EVENT_QUOTE_SENT,
    emit_automation_event,
)
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.proposal_builder import CatalogEntry, build_proposal_document
from app.services.quotes.proposal_pricing import price_christmas, price_permanent
from app.services.quotes.proposal_template import get_proposal_template

logger = structlog.get_logger()

# Statuses past which header/line edits and deletes are blocked: a quote the
# customer has decided on (or that lapsed) is a historical record.
_LOCKED_STATUSES = frozenset({"approved", "declined", "expired"})


class QuoteService:
    """Service for quote CRUD, lifecycle, and conversion to job/invoice."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="quote_service")

    # ------------------------------------------------------------------
    # Derivation helpers (pure; no I/O)
    # ------------------------------------------------------------------

    async def _emit_lifecycle_event(self, quote: Quote, event_type: str) -> None:
        """Queue a quote lifecycle event for automations (no commit).

        Shares the caller's transaction so the event is durable only if the
        transition itself commits. ``emit_automation_event`` no-ops when the
        workspace has no automation listening for ``event_type``.
        """
        await emit_automation_event(
            self.db,
            workspace_id=quote.workspace_id,
            event_type=event_type,
            contact_id=quote.contact_id,
            payload={
                "quote_id": str(quote.id),
                "number": quote.number,
                "status": quote.status,
                "total": float(quote.total or 0),
                "currency": quote.currency,
            },
        )

    def _recompute_totals(self, quote: Quote) -> None:
        """Recompute subtotal/total from line items in place.

        Requires ``quote.line_items`` to be loaded.
        """
        subtotal = round(sum(float(li.total) for li in quote.line_items), 2)
        quote.subtotal = subtotal
        quote.total = round(
            subtotal + float(quote.tax_amount or 0) - float(quote.discount_amount or 0), 2
        )

    @staticmethod
    def _line_total(quantity: float, unit_price: float, discount: float) -> float:
        return round(quantity * unit_price - discount, 2)

    async def _next_quote_number(self, workspace_id: uuid.UUID) -> str:
        """Allocate the next ``QUO-000001`` number for a workspace.

        Uses ``max(existing suffix) + 1`` so numbers stay monotonic even after a
        draft is deleted. Concurrent creates rely on the
        ``uq_quotes_workspace_number`` constraint as the final guard.
        """
        result = await self.db.execute(
            select(Quote.number).where(Quote.workspace_id == workspace_id)
        )
        max_seq = 0
        for number in result.scalars().all():
            try:
                max_seq = max(max_seq, int(number.rsplit("-", 1)[-1]))
            except (ValueError, IndexError):
                continue
        return f"QUO-{max_seq + 1:06d}"

    async def _expire_overdue(self, workspace_id: uuid.UUID) -> None:
        """Flip still-``sent`` quotes past their ``expiry_date`` to ``expired``.

        One scoped UPDATE keeps reads truthful without a background worker; it is
        idempotent and a no-op when nothing has lapsed.
        """
        await self.db.execute(
            update(Quote)
            .where(
                Quote.workspace_id == workspace_id,
                Quote.status == "sent",
                Quote.expiry_date.is_not(None),
                Quote.expiry_date < date.today(),
            )
            .values(status="expired")
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_quotes(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        contact_id: int | None = None,
    ) -> PaginatedQuotes:
        """List a workspace's quotes, newest first, with optional filters."""
        await self._expire_overdue(workspace_id)

        query = select(Quote).where(Quote.workspace_id == workspace_id)
        if status:
            query = query.where(Quote.status == status)
        if contact_id is not None:
            query = query.where(Quote.contact_id == contact_id)
        query = query.order_by(Quote.created_at.desc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=QuoteResponse,
            response_builder=PaginatedQuotes,
        )

    async def create_quote(
        self,
        workspace_id: uuid.UUID,
        quote_in: QuoteCreate,
        *,
        created_by_id: int | None = None,
    ) -> QuoteDetailResponse:
        """Create a draft quote with its initial line items and computed totals."""
        quote = Quote(
            workspace_id=workspace_id,
            contact_id=quote_in.contact_id,
            service_location_id=quote_in.service_location_id,
            opportunity_id=quote_in.opportunity_id,
            number=await self._next_quote_number(workspace_id),
            title=quote_in.title,
            currency=quote_in.currency,
            tax_amount=quote_in.tax_amount,
            discount_amount=quote_in.discount_amount,
            deposit_percentage=quote_in.deposit_percentage,
            issue_date=quote_in.issue_date,
            expiry_date=quote_in.expiry_date,
            notes=quote_in.notes,
            terms=quote_in.terms,
            status="draft",
            created_by_id=created_by_id,
        )
        for item in quote_in.line_items:
            quote.line_items.append(
                QuoteLineItem(
                    name=item.name,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount=item.discount,
                    total=self._line_total(item.quantity, item.unit_price, item.discount),
                )
            )

        self._recompute_totals(quote)
        self.db.add(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

        self.log.info(
            "quote_created",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            number=quote.number,
            total=float(quote.total),
        )
        return QuoteDetailResponse.model_validate(quote)

    async def get_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Fetch a single quote with its line items."""
        await self._expire_overdue(workspace_id)
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        return QuoteDetailResponse.model_validate(quote)

    async def update_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        quote_in: QuoteUpdate,
    ) -> QuoteDetailResponse:
        """Update quote header fields. Totals are re-derived, not set."""
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot edit a {quote.status} quote")

        for field in (
            "contact_id",
            "service_location_id",
            "opportunity_id",
            "title",
            "currency",
            "tax_amount",
            "discount_amount",
            "deposit_percentage",
            "issue_date",
            "expiry_date",
            "notes",
            "terms",
        ):
            value = getattr(quote_in, field)
            if value is not None:
                setattr(quote, field, value)

        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def delete_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> None:
        """Delete a draft/sent quote. Decided or expired quotes are kept."""
        quote = await get_or_404(self.db, Quote, quote_id, workspace_id=workspace_id)
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot delete a {quote.status} quote")
        await self.db.delete(quote)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    async def mark_sent(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Mark a quote as sent (sets ``sent_at`` once) and email it to the
        quote-to contact (best-effort)."""
        quote = await self._load_for_send(workspace_id, quote_id)
        await self._ensure_sent_state(quote)

        await self._email_quote(quote)
        return QuoteDetailResponse.model_validate(quote)

    async def _load_for_send(self, workspace_id: uuid.UUID, quote_id: uuid.UUID) -> Quote:
        return await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[
                selectinload(Quote.line_items),
                selectinload(Quote.contact),
                selectinload(Quote.workspace),
            ],
        )

    async def _ensure_sent_state(self, quote: Quote) -> None:
        """Transition a quote into ``sent`` (idempotent).

        Sets ``sent_at`` once and allocates the public proposal token once, on
        first send — re-sending keeps the same token so a link already in a
        customer's inbox never breaks.
        """
        if quote.status in {"approved", "declined"}:
            raise ConflictError(f"Cannot send a {quote.status} quote")
        if quote.sent_at is None:
            quote.sent_at = datetime.now(UTC)
        if quote.public_token is None:
            quote.public_token = generate_quote_token()
        already_sent = quote.status == "sent"
        quote.status = "sent"
        if not already_sent:
            await self._emit_lifecycle_event(quote, EVENT_QUOTE_SENT)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

    async def deliver_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        channel: str,
        to: str | None = None,
    ) -> QuoteDeliverResult:
        """Send the client proposal link by ``email`` or ``sms``.

        Transitions the quote to ``sent`` first (allocating its share token),
        then delivers. Destination precedence: explicit ``to`` → the wizard
        snapshot's client email/phone → the linked contact's. Raises
        ``ValidationError`` with an actionable message when a rail isn't ready
        (no destination, Telnyx unconfigured, no SMS-enabled number, opt-out).
        """
        from app.core.config import settings

        quote = await self._load_for_send(workspace_id, quote_id)
        await self._ensure_sent_state(quote)

        client = (quote.proposal_document or {}).get("client") or {}
        link = f"{settings.frontend_url.rstrip('/')}/p/quotes/{quote.public_token}"
        business = quote.workspace.name if quote.workspace else "our team"

        if channel == "email":
            email_to = (
                (to or "").strip()
                or (client.get("email") or "").strip()
                or (quote.contact.email if quote.contact else None)
            )
            if not email_to:
                raise ValidationError(
                    "No client email on this proposal — add one or pass a destination."
                )
            await self._email_quote(quote, override_email=email_to)
            self.log.info("quote_delivered", quote_id=str(quote.id), channel="email")
            return QuoteDeliverResult(ok=True, channel="email", to=email_to)

        if channel != "sms":
            raise ValidationError(f"Unknown delivery channel: {channel!r}")

        phone = (
            (to or "").strip()
            or (client.get("phone") or "").strip()
            or (quote.contact.phone_number if quote.contact else None)
        )
        if not phone:
            raise ValidationError(
                "No client phone on this proposal — add one or pass a destination."
            )
        if not settings.telnyx_api_key:
            raise ValidationError("Texting isn't configured (Telnyx API key missing).")

        from app.services.calendar.reminder_service import resolve_from_number
        from app.services.idempotency import derive_outbound_key
        from app.services.rate_limiting.opt_out_manager import OptOutManager
        from app.services.telephony.telnyx import TelnyxSMSService

        if await OptOutManager().check_opt_out(workspace_id, phone, self.db):
            raise ValidationError("This phone number has opted out of texts.")

        from_number = None
        if quote.contact_id is not None:
            from_number = await resolve_from_number(self.db, quote.contact_id, workspace_id, None)
        if not from_number:
            from_number = await self._any_sms_number(workspace_id)
        if not from_number:
            raise ValidationError(
                "No SMS-enabled phone number in this workspace — add one under Settings."
            )

        first = (client.get("first_name") or "").strip()
        greeting = f"Hi {first}, " if first else ""
        body = (
            f"{greeting}your lighting proposal from {business} is ready — "
            f"view and approve it here: {link}"
        )

        sms = TelnyxSMSService(settings.telnyx_api_key)
        try:
            await sms.send_message(
                to_number=phone,
                from_number=from_number,
                body=body,
                db=self.db,
                workspace_id=workspace_id,
                idempotency_key=derive_outbound_key(
                    "quote_sms", quote.id, phone, datetime.now(UTC).isoformat()
                ),
            )
        finally:
            await sms.close()
        self.log.info("quote_delivered", quote_id=str(quote.id), channel="sms")
        return QuoteDeliverResult(ok=True, channel="sms", to=phone)

    async def _any_sms_number(self, workspace_id: uuid.UUID) -> str | None:
        """Oldest active SMS-enabled workspace number (agentless fallback)."""
        from sqlalchemy import and_

        from app.models.phone_number import PhoneNumber

        result = await self.db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.workspace_id == workspace_id,
                    PhoneNumber.is_active.is_(True),
                    PhoneNumber.sms_enabled.is_(True),
                )
            )
            .order_by(PhoneNumber.created_at)
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        return str(phone) if phone else None

    async def approve_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Operator approves a quote on the customer's behalf."""
        await self._expire_overdue(workspace_id)
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status == "approved":
            return QuoteDetailResponse.model_validate(quote)
        if quote.status not in {"draft", "sent"}:
            raise ConflictError(f"Cannot approve a {quote.status} quote")
        quote.status = "approved"
        quote.approved_at = datetime.now(UTC)
        await self._emit_lifecycle_event(quote, EVENT_QUOTE_APPROVED)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info("quote_approved", quote_id=str(quote.id), workspace_id=str(workspace_id))
        return QuoteDetailResponse.model_validate(quote)

    async def decline_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        reason: str | None = None,
    ) -> QuoteDetailResponse:
        """Operator declines a quote on the customer's behalf."""
        await self._expire_overdue(workspace_id)
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status == "declined":
            return QuoteDetailResponse.model_validate(quote)
        if quote.status not in {"draft", "sent"}:
            raise ConflictError(f"Cannot decline a {quote.status} quote")
        quote.status = "declined"
        quote.declined_at = datetime.now(UTC)
        quote.decline_reason = reason
        await self._emit_lifecycle_event(quote, EVENT_QUOTE_DECLINED)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info("quote_declined", quote_id=str(quote.id), workspace_id=str(workspace_id))
        return QuoteDetailResponse.model_validate(quote)

    async def _email_quote(self, quote: Quote, *, override_email: str | None = None) -> None:
        """Email the quote's proposal link (best-effort; never raises).

        Destination: explicit override → wizard snapshot's client email → the
        linked contact's email. Wizard proposals usually have no Contact row,
        so the snapshot fallback is what makes their sends actually deliver.
        """
        from app.core.config import settings
        from app.services.email import send_quote_email
        from app.services.idempotency import derive_outbound_key

        client = (quote.proposal_document or {}).get("client") or {}
        contact_email = (
            (override_email or "").strip()
            or (client.get("email") or "").strip()
            or (quote.contact.email if quote.contact else None)
        )
        if not contact_email:
            self.log.info("quote_email_skipped_no_contact", quote_id=str(quote.id))
            return

        workspace_name = quote.workspace.name if quote.workspace else ""
        amount_str = f"{float(quote.total or 0):.2f} {quote.currency.upper()}"
        expiry = quote.expiry_date.isoformat() if quote.expiry_date else None
        # Link to the client-facing proposal page so the email is a doorway to a
        # branded, approvable proposal — not just a plain-text summary.
        proposal_url = (
            f"{settings.frontend_url.rstrip('/')}/p/quotes/{quote.public_token}"
            if quote.public_token
            else None
        )

        try:
            await send_quote_email(
                to_email=contact_email,
                workspace_name=workspace_name,
                quote_number=quote.number,
                amount_str=amount_str,
                title=quote.title,
                expiry_date=expiry,
                notes=quote.notes,
                proposal_url=proposal_url,
                idempotency_key=derive_outbound_key("quote_send", quote.id, contact_email),
            )
        except Exception as exc:  # pragma: no cover - best-effort email
            self.log.warning("quote_email_failed", quote_id=str(quote.id), error=str(exc))

    # ------------------------------------------------------------------
    # Public client proposal (no auth, token-keyed)
    # ------------------------------------------------------------------

    async def _load_by_token(self, token: str) -> Quote:
        """Load a sent quote by its public token, or raise ``NotFoundError``.

        Drafts have no token and never resolve; an unknown token 404s. Expiry is
        applied lazily so a lapsed proposal reads (and behaves) truthfully.
        """
        result = await self.db.execute(
            select(Quote)
            .where(Quote.public_token == token)
            .options(
                selectinload(Quote.line_items),
                selectinload(Quote.contact),
                selectinload(Quote.workspace),
            )
        )
        quote = result.scalar_one_or_none()
        if quote is None or quote.status == "draft":
            raise NotFoundError("Proposal not found")
        if (
            quote.status == "sent"
            and quote.expiry_date is not None
            and quote.expiry_date < date.today()
        ):
            quote.status = "expired"
            await self.db.commit()
            await self.db.refresh(quote, ["line_items"])
        return quote

    async def get_public_proposal(self, token: str) -> PublicProposal:
        """Return the read-only, safe-fields-only proposal for a public token."""
        quote = await self._load_by_token(token)
        template = get_proposal_template(quote.workspace)
        business_name = template.business_name or (quote.workspace.name if quote.workspace else "")
        client_name: str | None = None
        if quote.contact is not None:
            client_name = quote.contact.full_name or quote.contact.first_name

        total = float(quote.total or 0)
        deposit_pct = (
            float(quote.deposit_percentage) if quote.deposit_percentage is not None else None
        )
        deposit_amount = round(total * deposit_pct / 100, 2) if deposit_pct else None

        return PublicProposal(
            token=token,
            number=quote.number,
            title=quote.title,
            status=quote.status,
            currency=quote.currency,
            subtotal=float(quote.subtotal or 0),
            tax_amount=float(quote.tax_amount or 0),
            discount_amount=float(quote.discount_amount or 0),
            total=total,
            issue_date=quote.issue_date,
            expiry_date=quote.expiry_date,
            is_expired=quote.status == "expired",
            is_decided=quote.status in {"approved", "declined", "expired"},
            intro=template.intro,
            notes=quote.notes,
            terms=quote.terms or template.default_terms,
            client_name=client_name,
            deposit_percentage=deposit_pct,
            deposit_amount=deposit_amount,
            deposit_paid=quote.deposit_paid_at is not None,
            proposal_document=quote.proposal_document,
            line_items=[
                PublicProposalLineItem(
                    name=li.name,
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_price=float(li.unit_price),
                    discount=float(li.discount),
                    total=float(li.total),
                )
                for li in quote.line_items
            ],
            branding=PublicProposalBranding(
                business_name=business_name,
                logo_url=template.logo_url,
                brand_color=template.brand_color,
                accent_color=template.accent_color,
                business_address=template.business_address,
                business_phone=template.business_phone,
                business_email=template.business_email,
                footer=template.footer,
            ),
        )

    async def approve_public(self, token: str) -> PublicProposalActionResult:
        """Client approves their proposal via the public token (idempotent).

        Reuses the operator approve path so the same lifecycle guards and
        automation event fire; an expired/declined proposal is rejected there.
        """
        quote = await self._load_by_token(token)
        result = await self.approve_quote(quote.workspace_id, quote.id)
        return PublicProposalActionResult(
            token=token,
            status=result.status,
            message="Thank you! Your proposal has been approved.",
        )

    async def decline_public(
        self, token: str, *, reason: str | None = None
    ) -> PublicProposalActionResult:
        """Client declines their proposal via the public token (idempotent)."""
        quote = await self._load_by_token(token)
        result = await self.decline_quote(quote.workspace_id, quote.id, reason=reason)
        return PublicProposalActionResult(
            token=token,
            status=result.status,
            message="Your response has been recorded. Thank you.",
        )

    # ------------------------------------------------------------------
    # Sales wizard (config-driven multi-tier proposal builder)
    # ------------------------------------------------------------------

    async def _resolve_wizard_catalog(self, workspace_id: uuid.UUID) -> dict[str, CatalogEntry]:
        """Load active catalog items, keyed by their stable id (``sku`` or id).

        Tiers in the pricing config and the wizard's quantities both reference an
        item by this key, so the seed sets each fixture's ``sku`` to a stable key.
        """
        result = await self.db.execute(
            select(CatalogItem).where(
                CatalogItem.workspace_id == workspace_id,
                CatalogItem.is_active.is_(True),
            )
        )
        entries: dict[str, CatalogEntry] = {}
        for item in result.scalars().all():
            key = item.sku or str(item.id)
            attrs = item.attributes or {}
            entries[key] = CatalogEntry(
                item_id=key,
                name=item.name,
                unit_price=Decimal(str(item.unit_price)),
                transformer=bool(attrs.get("transformer")),
                components=list(item.components or []),
            )
        return entries

    @staticmethod
    def _wizard_title(document: ProposalDocument) -> str:
        """A sensible default title from the client's name."""
        client = document.client
        if client and (client.last_name or client.first_name):
            who = client.last_name or client.first_name
            return f"The {who} Residence — Lighting Proposal"
        return "Lighting Proposal"

    async def preview_from_wizard(
        self,
        workspace_id: uuid.UUID,
        payload: ProposalWizardPayload,
    ) -> ProposalDocument:
        """Compute the full proposal document without persisting (live preview).

        Same code path as save, so the previewed numbers are exactly what gets
        stored. The client submits only a selection; all money is server-computed.
        """
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        config = get_pricing_config(workspace)
        catalog = await self._resolve_wizard_catalog(workspace_id)
        document, _ = build_proposal_document(config, catalog, payload)
        return document

    async def save_from_wizard(
        self,
        workspace_id: uuid.UUID,
        payload: ProposalWizardPayload,
        *,
        created_by_id: int | None = None,
    ) -> QuoteDetailResponse:
        """Persist a wizard proposal: a draft quote whose headline-tier lines are
        recomputed server-side, plus the rich multi-tier snapshot on
        ``proposal_document``. Client totals are never trusted.
        """
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        config = get_pricing_config(workspace)
        catalog = await self._resolve_wizard_catalog(workspace_id)
        document, line_items = build_proposal_document(config, catalog, payload)

        quote = Quote(
            workspace_id=workspace_id,
            contact_id=payload.contact_id,
            service_location_id=payload.service_location_id,
            opportunity_id=payload.opportunity_id,
            number=await self._next_quote_number(workspace_id),
            title=payload.title or self._wizard_title(document),
            currency="USD",
            notes=payload.notes,
            terms=payload.terms,
            status="draft",
            proposal_document=document.model_dump(mode="json"),
            created_by_id=created_by_id,
        )
        for item in line_items:
            quote.line_items.append(
                QuoteLineItem(
                    name=item.name,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount=item.discount,
                    total=self._line_total(item.quantity, item.unit_price, item.discount),
                )
            )
        self._recompute_totals(quote)
        self.db.add(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info(
            "quote_saved_from_wizard",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            number=quote.number,
            total=float(quote.total),
            selected_tier=document.selected_tier,
        )
        return QuoteDetailResponse.model_validate(quote)

    # ------------------------------------------------------------------
    # Roofline estimator + permanent-vs-temporary comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_comparison(
        config: PricingSettings, req: LinearFeetEstimateRequest
    ) -> LinearFeetEstimateResult:
        """Price permanent vs seasonal for a measured roofline (pure given config).

        Every dollar is computed server-side from the workspace pricing config; the
        rep's ``feet`` is the only untrusted input. Multi-year savings project the
        seasonal (temporary) cost over ``comparison_years`` seasons against
        permanent's one-time cost — the "pay once vs every season" pitch.
        """
        perm = price_permanent(config, feet=req.feet, channels=req.channels)
        xmas = price_christmas(
            config,
            roofline_feet=req.feet,
            takedown=req.takedown,
            storage=req.storage,
        )
        perm_enabled = bool(config.permanent.enabled)
        xmas_enabled = bool(config.christmas.enabled)
        perm_total = float(perm.total) if perm_enabled else 0.0
        xmas_total = float(xmas.total) if xmas_enabled else 0.0

        years = int(config.comparison_years)
        temporary_multi_year = round(xmas_total * years, 2)
        permanent_one_time = perm_total
        # Only a meaningful figure when both options are actually offered.
        multi_year_savings = (
            round(temporary_multi_year - permanent_one_time, 2)
            if (perm_enabled and xmas_enabled)
            else 0.0
        )
        difference = (
            round(abs(perm_total - xmas_total), 2) if (perm_enabled and xmas_enabled) else 0.0
        )

        return LinearFeetEstimateResult(
            feet=float(req.feet),
            permanent=PermanentEstimate(
                enabled=perm_enabled, total=perm_total, per_ft=float(config.permanent.per_ft)
            ),
            christmas=ChristmasEstimate(enabled=xmas_enabled, total=xmas_total),
            difference=difference,
            years=years,
            temporary_multi_year=temporary_multi_year,
            permanent_one_time=permanent_one_time,
            multi_year_savings=multi_year_savings,
            permanent_perks=list(config.permanent.perks),
            christmas_perks=list(config.christmas.perks),
        )

    async def estimate_linear_feet(
        self,
        workspace_id: uuid.UUID,
        req: LinearFeetEstimateRequest,
    ) -> LinearFeetEstimateResult:
        """Compute a permanent-vs-temporary estimate for a measured roofline.

        Authenticated rep tool: the result carries ``feet`` (internal) plus both
        totals and the multi-year savings. No persistence.
        """
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        config = get_pricing_config(workspace)
        return self._compute_comparison(config, req)

    async def share_comparison(
        self,
        workspace_id: uuid.UUID,
        req: ComparisonShareRequest,
        *,
        created_by_id: int | None = None,
    ) -> ComparisonShareResult:
        """Persist a comparison behind a token and return the client-facing URL.

        Only the measured inputs are stored; prices are recomputed from live config
        on every public view so a rate change is always reflected.
        """
        await get_or_404(self.db, Workspace, workspace_id)
        comparison = RooflineComparison(
            workspace_id=workspace_id,
            feet=float(req.feet),
            channels=int(req.channels),
            takedown=bool(req.takedown),
            storage=bool(req.storage),
            client_name=req.client_name,
            label=req.label,
            created_by_id=created_by_id,
        )
        self.db.add(comparison)
        await self.db.commit()
        await self.db.refresh(comparison)

        from app.core.config import settings

        url = f"{settings.frontend_url.rstrip('/')}/p/compare/{comparison.public_token}"
        self.log.info(
            "roofline_comparison_shared",
            comparison_id=str(comparison.id),
            workspace_id=str(workspace_id),
        )
        return ComparisonShareResult(token=comparison.public_token, url=url)

    async def get_public_comparison(self, token: str) -> PublicComparison:
        """Return the safe, feet-free comparison for a public token.

        Recomputes prices from the workspace's live pricing config. The public
        payload deliberately excludes linear feet, per-foot rate, and zone counts.
        """
        result = await self.db.execute(
            select(RooflineComparison)
            .where(RooflineComparison.public_token == token)
            .options(selectinload(RooflineComparison.workspace))
        )
        comparison = result.scalar_one_or_none()
        if comparison is None:
            raise NotFoundError("Comparison not found")

        workspace = comparison.workspace
        config = get_pricing_config(workspace)
        template = get_proposal_template(workspace)
        computed = self._compute_comparison(
            config,
            LinearFeetEstimateRequest(
                feet=comparison.feet,
                channels=comparison.channels,
                takedown=comparison.takedown,
                storage=comparison.storage,
            ),
        )

        return PublicComparison(
            business_name=template.business_name or (workspace.name if workspace else ""),
            brand_color=template.brand_color,
            accent_color=template.accent_color,
            logo_url=template.logo_url,
            client_name=comparison.client_name,
            currency="USD",
            permanent=PublicPermanentComparison(
                enabled=computed.permanent.enabled, total=computed.permanent.total
            ),
            christmas=PublicChristmasComparison(
                enabled=computed.christmas.enabled, total=computed.christmas.total
            ),
            difference=computed.difference,
            years=computed.years,
            temporary_multi_year=computed.temporary_multi_year,
            permanent_one_time=computed.permanent_one_time,
            multi_year_savings=computed.multi_year_savings,
            permanent_perks=computed.permanent_perks,
            christmas_perks=computed.christmas_perks,
        )

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    async def convert_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        create_job: bool = True,
        create_invoice: bool = True,
    ) -> QuoteConvertResponse:
        """Convert an approved quote into a job and/or an invoice (idempotent).

        Re-running returns the already-linked job/invoice rather than creating
        duplicates. A job needs a ``contact_id``; converting to an invoice copies
        the quote's line items verbatim.
        """
        from app.services.invoices import InvoiceService
        from app.services.jobs import JobService

        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status != "approved":
            raise ConflictError("Only an approved quote can be converted")

        job_id = quote.converted_job_id
        invoice_id = quote.converted_invoice_id
        prior_job_id = job_id
        prior_invoice_id = invoice_id

        # Create the invoice first so the job can be linked to it for costing
        # (its profitability reads revenue from the linked invoice).
        if create_invoice and invoice_id is None:
            invoice = await InvoiceService(self.db).create_invoice(
                workspace_id,
                InvoiceCreate(
                    contact_id=quote.contact_id,
                    opportunity_id=quote.opportunity_id,
                    currency=quote.currency,
                    tax_amount=float(quote.tax_amount or 0),
                    discount_amount=float(quote.discount_amount or 0),
                    notes=quote.notes,
                    terms=quote.terms,
                    line_items=[
                        InvoiceLineItemCreate(
                            name=li.name,
                            description=li.description,
                            quantity=float(li.quantity),
                            unit_price=float(li.unit_price),
                            discount=float(li.discount),
                        )
                        for li in quote.line_items
                    ],
                ),
                created_by_id=quote.created_by_id,
            )
            invoice_id = invoice.id
            quote.converted_invoice_id = invoice_id

        if create_job and job_id is None:
            if quote.contact_id is None:
                raise ConflictError("Cannot create a job from a quote with no contact")
            job = await JobService(self.db).create(
                workspace_id,
                {
                    "contact_id": quote.contact_id,
                    "service_location_id": quote.service_location_id,
                    "title": quote.title or f"Quote {quote.number}",
                    "description": quote.notes,
                    # Link the job to the just-created invoice (or a previously
                    # converted one) so its P&L has a revenue side.
                    "invoice_id": invoice_id,
                    "technician_ids": [],
                },
            )
            job_id = job.id
            quote.converted_job_id = job_id

        # Emit only when this call actually converted something — re-running an
        # already-converted quote is a no-op and must not re-fire the event.
        if job_id != prior_job_id or invoice_id != prior_invoice_id:
            await emit_automation_event(
                self.db,
                workspace_id=quote.workspace_id,
                event_type=EVENT_QUOTE_CONVERTED,
                contact_id=quote.contact_id,
                payload={
                    "quote_id": str(quote.id),
                    "number": quote.number,
                    "job_id": str(job_id) if job_id else None,
                    "invoice_id": str(invoice_id) if invoice_id else None,
                },
            )

        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

        self.log.info(
            "quote_converted",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            job_id=str(job_id) if job_id else None,
            invoice_id=str(invoice_id) if invoice_id else None,
        )
        return QuoteConvertResponse(
            quote=QuoteDetailResponse.model_validate(quote),
            job_id=job_id,
            invoice_id=invoice_id,
        )

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    async def add_line_item(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        item_in: QuoteLineItemCreate,
    ) -> QuoteDetailResponse:
        """Add a line item and recompute quote totals."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        quote.line_items.append(
            QuoteLineItem(
                name=item_in.name,
                description=item_in.description,
                quantity=item_in.quantity,
                unit_price=item_in.unit_price,
                discount=item_in.discount,
                total=self._line_total(item_in.quantity, item_in.unit_price, item_in.discount),
            )
        )
        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def update_line_item(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        item_id: uuid.UUID,
        item_in: QuoteLineItemUpdate,
    ) -> QuoteDetailResponse:
        """Update a line item, recompute its total and the quote totals."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        line_item = await get_nested_or_404(
            self.db,
            QuoteLineItem,
            item_id,
            parent_field="quote_id",
            parent_id=quote_id,
            detail="Line item not found",
        )

        if item_in.name is not None:
            line_item.name = item_in.name
        if item_in.description is not None:
            line_item.description = item_in.description
        if item_in.quantity is not None:
            line_item.quantity = item_in.quantity
        if item_in.unit_price is not None:
            line_item.unit_price = item_in.unit_price
        if item_in.discount is not None:
            line_item.discount = item_in.discount
        line_item.total = self._line_total(
            float(line_item.quantity), float(line_item.unit_price), float(line_item.discount)
        )

        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def remove_line_item(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Remove a line item and recompute quote totals."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        line_item = await get_nested_or_404(
            self.db,
            QuoteLineItem,
            item_id,
            parent_field="quote_id",
            parent_id=quote_id,
            detail="Line item not found",
        )
        quote.line_items.remove(line_item)
        await self.db.delete(line_item)
        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def _get_mutable_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> Quote:
        """Load a quote (with line items) and reject edits once decided/expired."""
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot edit line items on a {quote.status} quote")
        return quote
