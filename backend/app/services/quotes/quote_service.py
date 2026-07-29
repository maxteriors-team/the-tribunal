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
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import ServiceLocation
from app.models.opportunity import Opportunity
from app.models.quote import Quote, QuoteLineItem, generate_quote_token
from app.models.roofline_comparison import RooflineComparison
from app.models.workspace import Workspace
from app.schemas.estimate import (
    ChristmasEstimate,
    ComparisonDeliverResult,
    ComparisonShareRequest,
    ComparisonShareResult,
    EstimateQuoteRequest,
    EstimateRenderRequest,
    EstimateRenderResult,
    LinearFeetEstimateRequest,
    LinearFeetEstimateResult,
    PermanentEstimate,
    PublicChristmasComparison,
    PublicComparison,
    PublicComparisonPackage,
    PublicPermanentComparison,
    PublicRooflineComparison,
)
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.schemas.pricing import (
    ChristmasPackagePricing,
    ChristmasPricing,
    PermanentPricing,
    PricingSettings,
)
from app.schemas.proposal import (
    PublicProposal,
    PublicProposalActionResult,
    PublicProposalBranding,
    PublicProposalLineItem,
    PublicProposalPackage,
)
from app.schemas.proposal_wizard import (
    ProposalDocument,
    ProposalWizardPayload,
    client_safe_document,
)
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
from app.services.notifications import notify_workspace_event
from app.services.quotes.attach_metrics import compute_attach_metrics
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.proposal_builder import (
    CatalogEntry,
    build_proposal_document,
    reselect_tier,
    select_tier,
    sellable_tier_keys,
)
from app.services.quotes.proposal_pricing import (
    price_christmas,
    price_christmas_package,
    price_christmas_packages,
    price_permanent,
)
from app.services.quotes.proposal_template import get_proposal_template
from app.services.recurring_jobs.service_plan_provisioner import ServicePlanProvisioner

logger = structlog.get_logger()


def _resolve_recommended_package(
    packages: list[ChristmasPackagePricing],
    selected_key: str | None,
) -> ChristmasPackagePricing | None:
    """The seasonal package to steer the client toward.

    Mirrors the frontend ``resolveSelectedPackage``: the rep's explicit pick when
    it names a priced package, else the most-inclusive tier (last in
    ``package_order``, which :func:`price_christmas_packages` emits low→high).
    ``None`` when the workspace sells no seasonal packages.
    """
    if not packages:
        return None
    if selected_key:
        for pkg in packages:
            if pkg.key == selected_key:
                return pkg
    return packages[-1]


def build_public_comparison_packages(
    packages: list[ChristmasPackagePricing],
    selected_key: str | None,
) -> list[PublicComparisonPackage]:
    """Map priced seasonal packages to the feet-free public card payload.

    Only each package's ``total`` crosses the public boundary — never the
    :class:`ChristmasPricing` breakdown (which carries ``roofline_feet`` /
    ``roofline_cost``), so a measurement cannot leak to the homeowner. The
    recommended tier is flagged for a highlight, not a gate.
    """
    recommended = _resolve_recommended_package(packages, selected_key)
    return [
        PublicComparisonPackage(
            key=pkg.key,
            label=pkg.label,
            name=pkg.name,
            marker=pkg.marker,
            experience=pkg.experience,
            points=list(pkg.points),
            value_tag=pkg.value_tag,
            popular=pkg.popular,
            includes_roofline=pkg.includes_roofline,
            total=pkg.pricing.total,
            recommended=recommended is not None and pkg.key == recommended.key,
        )
        for pkg in packages
    ]


def build_public_roofline_comparison(
    config: PricingSettings,
    computed: LinearFeetEstimateResult,
) -> PublicRooflineComparison | None:
    """Roofline-only, like-for-like cost comparison for the public page.

    ``None`` unless the workspace opted in via ``roofline_comparison_enabled``
    **and** both services are offered — so every existing workspace and every
    already-shared link renders exactly as it does today.

    The headline seasonal total can include decor (trees/bushes/wreaths), which
    makes it apples-to-oranges against permanent's roofline track; this block
    compares roofline to roofline. It deliberately uses the *à la carte* seasonal
    roofline cost rather than the recommended package's: a package with
    ``includes_roofline=False`` prices ``roofline_cost == 0``, which would render
    a misleading $0. The à la carte figure is the true "what the roofline alone
    costs each season" and is always well-defined. Feet-free — costs only.
    """
    if not config.roofline_comparison_enabled:
        return None
    if not (computed.permanent.enabled and computed.christmas.enabled):
        return None

    permanent_total = round(float(computed.permanent.roofline_cost), 2)
    seasonal_total = round(float(computed.christmas.roofline_cost), 2)
    seasonal_multi_year = round(seasonal_total * computed.years, 2)
    return PublicRooflineComparison(
        permanent_total=permanent_total,
        seasonal_total=seasonal_total,
        seasonal_multi_year=seasonal_multi_year,
        savings=round(seasonal_multi_year - permanent_total, 2),
    )


# Statuses past which header/line edits and deletes are blocked: a quote the
# customer has decided on (or that lapsed) is a historical record.
_LOCKED_STATUSES = frozenset({"approved", "declined", "expired"})


def _fmt_qty(qty: object) -> str:
    """Render a fulfillment quantity for a human: ``2`` not ``2.0``, ``1.5`` intact."""
    try:
        return f"{float(qty):g}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    """Split a free-text name into (first, last); either may be None.

    Used to seed a new contact from the estimator's single ``client_name`` field.
    A lone token becomes the first name; everything after the first space is the
    last name. Blank/None yields ``(None, None)`` so the caller's own default
    first name applies.
    """
    parts = (full_name or "").strip().split(" ", 1)
    first = parts[0] if parts and parts[0] else None
    last = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return first, last


class QuoteService:
    """Service for quote CRUD, lifecycle, and conversion to job/invoice."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="quote_service")

    # ------------------------------------------------------------------
    # Reference validation (tenant-safe)
    # ------------------------------------------------------------------

    async def _validate_refs(
        self,
        workspace_id: uuid.UUID,
        *,
        contact_id: int | None = None,
        service_location_id: uuid.UUID | None = None,
        opportunity_id: uuid.UUID | None = None,
    ) -> None:
        """Validate client-supplied references belong to ``workspace_id``.

        Only ids that were actually supplied are checked. A foreign id 404s
        exactly like a missing one, so a caller cannot bind a quote to another
        tenant's contact and have the platform email/SMS that contact (which
        would echo their decrypted details back in the response).
        """
        if contact_id is not None:
            await assert_workspace_owned(
                self.db, Contact, contact_id, workspace_id, detail="Contact not found"
            )
        if service_location_id is not None:
            await assert_workspace_owned(
                self.db,
                ServiceLocation,
                service_location_id,
                workspace_id,
                detail="Service location not found",
            )
        if opportunity_id is not None:
            await assert_workspace_owned(
                self.db,
                Opportunity,
                opportunity_id,
                workspace_id,
                detail="Opportunity not found",
            )

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
        """Recompute every line-item-derived field on the quote, in place.

        Totals *and* the denormalized attach metrics, because both are functions
        of the same line items. Keeping them in one method is deliberate: this is
        already called by every path that adds, edits, replaces or removes a line,
        so the metrics cannot drift by someone adding a mutation path and
        forgetting a second call.

        Requires ``quote.line_items`` to be loaded.
        """
        subtotal = round(sum(float(li.total) for li in quote.line_items), 2)
        quote.subtotal = subtotal
        quote.total = round(
            subtotal + float(quote.tax_amount or 0) - float(quote.discount_amount or 0), 2
        )
        primary, attach_count, attach_value = compute_attach_metrics(quote.line_items)
        quote.primary_service = primary
        quote.attach_count = attach_count
        quote.attach_value = attach_value

    @staticmethod
    def _line_total(quantity: float, unit_price: float, discount: float) -> float:
        return round(quantity * unit_price - discount, 2)

    async def _catalog_categories(
        self,
        workspace_id: uuid.UUID,
        items: Sequence[QuoteLineItemCreate],
    ) -> Mapping[uuid.UUID, str | None]:
        """Look up the service category of every price-book item being copied.

        One scoped query for the whole payload rather than per line. Scoped to
        the workspace on purpose: a ``catalog_item_id`` from another tenant
        resolves to nothing instead of leaking that workspace's categories.
        Returns an empty map when no line came from the picker.
        """
        ids = {item.catalog_item_id for item in items if item.catalog_item_id is not None}
        if not ids:
            return {}
        result = await self.db.execute(
            select(CatalogItem.id, CatalogItem.service_category).where(
                CatalogItem.workspace_id == workspace_id,
                CatalogItem.id.in_(ids),
            )
        )
        return {row.id: row.service_category for row in result}

    def _build_line_item(
        self,
        item: QuoteLineItemCreate,
        categories: Mapping[uuid.UUID, str | None] | None = None,
    ) -> QuoteLineItem:
        """Build a line item with its server-computed total and category snapshot.

        The category is copied from the picked catalog item (via ``categories``,
        as resolved by :meth:`_catalog_categories`) and never read from the
        request body. A line typed by hand, built by the wizard, or pointing at a
        catalog item that has since been deleted stays uncategorized — that is a
        normal outcome, not an error, and attach metrics simply skip it.
        """
        source_id = item.catalog_item_id
        service_category = (
            categories.get(source_id) if categories is not None and source_id is not None else None
        )
        return QuoteLineItem(
            name=item.name,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount=item.discount,
            total=self._line_total(item.quantity, item.unit_price, item.discount),
            service_category=service_category,
        )

    @staticmethod
    def _wizard_deposit_selection(
        payload: ProposalWizardPayload, config: PricingSettings
    ) -> tuple[str, float] | None:
        """Resolve the wizard's deposit (mode, value): payload first, else the
        workspace default. Returns None when no deposit applies."""
        sel = payload.deposit
        if sel is not None and sel.value > 0:
            return sel.mode, float(sel.value)
        default = config.deposit
        if default.enabled and default.value > 0:
            return default.mode, float(default.value)
        return None

    def _attach_deposit_to_document(
        self,
        document: ProposalDocument,
        payload: ProposalWizardPayload,
        config: PricingSettings,
    ) -> None:
        """Set the document's display deposit from the resolved selection.

        Deposit is taken on the selected (financed) all-in total so the preview
        shows the client exactly what's due today. No-op when no deposit applies.
        """
        from app.services.payments.quote_deposit_service import resolve_deposit

        selection = self._wizard_deposit_selection(payload, config)
        if selection is None:
            return
        mode, value = selection
        total = float(document.grand_financed_total or 0)
        document.deposit_mode = mode
        document.deposit_value = value
        document.deposit_amount = resolve_deposit(mode, value, total)

    async def _resolve_wizard_contact(
        self,
        workspace_id: uuid.UUID,
        payload: ProposalWizardPayload,
    ) -> int | None:
        """Find or create the quote-to contact from the wizard's client details."""
        client = payload.client
        if client is None:
            return None
        return await self._resolve_or_create_contact(
            workspace_id,
            first_name=client.first_name,
            last_name=client.last_name,
            email=client.email,
            phone=client.phone,
            source="sales_wizard",
        )

    async def _resolve_or_create_contact(
        self,
        workspace_id: uuid.UUID,
        *,
        first_name: str | None,
        last_name: str | None,
        email: str | None,
        phone: str | None,
        source: str,
    ) -> int | None:
        """Find or create a workspace contact from loose client details.

        Contacts are phone-keyed in this CRM (``phone_hash`` is required), so a
        new contact is only created when a phone is present. Matching prefers a
        hashed email, then a hashed phone, so re-saving the same client never
        duplicates them. Returns None when there's nothing to match or create on
        (e.g. an email-only client) — the caller stays saved, just unlinked.

        Shared by the sales wizard and the roofline estimator so both attach
        their output to the same customer record with identical dedupe rules.
        """
        email = (email or "").strip() or None
        phone = (phone or "").strip() or None

        from app.core.encryption import hash_phone, hash_value

        if email:
            match = await self.db.execute(
                select(Contact).where(
                    Contact.workspace_id == workspace_id,
                    Contact.email_hash == hash_value(email),
                )
            )
            found = match.scalars().first()
            if found is not None:
                return found.id
        if phone:
            match = await self.db.execute(
                select(Contact).where(
                    Contact.workspace_id == workspace_id,
                    Contact.phone_hash == hash_phone(phone),
                )
            )
            found = match.scalars().first()
            if found is not None:
                return found.id

        # Only create when we can satisfy the required phone identity key.
        if phone is None:
            return None
        from app.services.contacts.contact_service import ContactService

        service = ContactService(self.db)
        contact = await service.create_contact(
            workspace_id,
            first_name=(first_name or "").strip() or "Client",
            last_name=(last_name or "").strip() or None,
            email=email,
            phone_number=phone,
            source=source,
        )
        return contact.id

    @staticmethod
    def _apply_default_deposit(quote: Quote, workspace: Workspace) -> None:
        """Set the workspace's default deposit on a quote that requests none.

        Reads the pricing config's ``DepositConfig``; a percentage default maps to
        ``deposit_percentage`` and a fixed default to ``deposit_amount_fixed``.
        No-op when the config's deposit is disabled or zero.
        """
        config = get_pricing_config(workspace)
        deposit = config.deposit
        if not deposit.enabled or deposit.value <= 0:
            return
        if deposit.mode == "fixed":
            quote.deposit_amount_fixed = round(float(deposit.value), 2)
        else:
            quote.deposit_percentage = min(100.0, round(float(deposit.value), 2))

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
        await self._validate_refs(
            workspace_id,
            contact_id=quote_in.contact_id,
            service_location_id=quote_in.service_location_id,
            opportunity_id=quote_in.opportunity_id,
        )
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
            deposit_amount_fixed=quote_in.deposit_amount_fixed,
            issue_date=quote_in.issue_date,
            expiry_date=quote_in.expiry_date,
            notes=quote_in.notes,
            terms=quote_in.terms,
            status="draft",
            created_by_id=created_by_id,
        )
        # Inherit the workspace's default deposit when the operator set none.
        if quote.deposit_percentage is None and quote.deposit_amount_fixed is None:
            workspace = await get_or_404(self.db, Workspace, workspace_id)
            self._apply_default_deposit(quote, workspace)
        categories = await self._catalog_categories(workspace_id, quote_in.line_items)
        for item in quote_in.line_items:
            quote.line_items.append(self._build_line_item(item, categories))

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

        await self._validate_refs(
            workspace_id,
            contact_id=quote_in.contact_id,
            service_location_id=quote_in.service_location_id,
            opportunity_id=quote_in.opportunity_id,
        )

        for field in (
            "contact_id",
            "service_location_id",
            "opportunity_id",
            "title",
            "currency",
            "tax_amount",
            "discount_amount",
            "deposit_percentage",
            "deposit_amount_fixed",
            "issue_date",
            "expiry_date",
            "notes",
            "terms",
        ):
            value = getattr(quote_in, field)
            if value is not None:
                setattr(quote, field, value)

        # Deposit modes are mutually exclusive: setting one clears the other so a
        # switch from percentage to fixed (or back) never leaves both populated.
        if quote_in.deposit_amount_fixed is not None:
            quote.deposit_percentage = None
        elif quote_in.deposit_percentage is not None:
            quote.deposit_amount_fixed = None

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
        first = (client.get("first_name") or "").strip()
        greeting = f"Hi {first}, " if first else ""
        await self._text_client_link(
            workspace_id,
            phone=phone,
            contact_id=quote.contact_id,
            body=(
                f"{greeting}your lighting proposal from {business} is ready — "
                f"view and approve it here: {link}"
            ),
            idempotency_scope="quote_sms",
            idempotency_id=quote.id,
        )
        self.log.info("quote_delivered", quote_id=str(quote.id), channel="sms")
        return QuoteDeliverResult(ok=True, channel="sms", to=phone)

    async def _text_client_link(
        self,
        workspace_id: uuid.UUID,
        *,
        phone: str,
        contact_id: int | None,
        body: str,
        idempotency_scope: str,
        idempotency_id: uuid.UUID,
    ) -> None:
        """Text a client-facing link, or raise ``ValidationError`` saying why not.

        Shared by proposal and estimate delivery so both honour the same rails:
        Telnyx configured, the number hasn't opted out, and the workspace owns an
        SMS-capable sender. Every refusal names the fix, because a rep watching a
        button fail can act on "add a number under Settings" and cannot act on a
        generic send error.

        The sender follows the contact's own conversation when there is one, so a
        homeowner sees the number that has been texting them all along rather
        than a stranger's.
        """
        from app.core.config import settings
        from app.services.calendar.reminder_service import resolve_from_number
        from app.services.idempotency import derive_outbound_key
        from app.services.rate_limiting.opt_out_manager import OptOutManager
        from app.services.telephony.telnyx import TelnyxSMSService

        if not settings.telnyx_api_key:
            raise ValidationError("Texting isn't configured (Telnyx API key missing).")

        if await OptOutManager().check_opt_out(workspace_id, phone, self.db):
            raise ValidationError("This phone number has opted out of texts.")

        from_number = None
        if contact_id is not None:
            from_number = await resolve_from_number(self.db, contact_id, workspace_id, None)
        if not from_number:
            from_number = await self._any_sms_number(workspace_id)
        if not from_number:
            raise ValidationError(
                "No SMS-enabled phone number in this workspace — add one under Settings."
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
                    idempotency_scope,
                    idempotency_id,
                    phone,
                    datetime.now(UTC).isoformat(),
                ),
            )
        finally:
            await sms.close()

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
        # Approval is the moment the client signed up, so their Care Plan or
        # Christmas season becomes a Service Plan here, *inside* the approval
        # transaction: a silently missing plan is lost recurring revenue, which
        # makes it data rather than a best-effort side effect like the parts
        # notification below. Re-approving a quote provisions nothing new.
        await ServicePlanProvisioner(self.db).provision_from_quote(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info("quote_approved", quote_id=str(quote.id), workspace_id=str(workspace_id))
        await self._notify_fulfillment_parts(quote)
        return QuoteDetailResponse.model_validate(quote)

    async def _notify_fulfillment_parts(self, quote: Quote) -> None:
        """Email the workspace the distributor parts list for an approved quote.

        The approved quote's ``proposal_document.fulfillment`` is the aggregated
        SKU bill-of-materials for the selected tier — the list someone has to hand
        the distributor to actually order the job. Sending it on approval turns a
        buried JSONB field into the order sheet.

        Best-effort and post-commit: the approval already succeeded and must not
        be rolled back by a mail failure. Silent no-op when the quote carries no
        parts (a flat, non-wizard quote).
        """
        document = quote.proposal_document or {}
        raw_parts = document.get("fulfillment") or []
        parts = [p for p in raw_parts if isinstance(p, dict) and str(p.get("sku") or "").strip()]
        if not parts:
            return

        # ``derive_outbound_key`` inside the notifier dedupes per (event, user),
        # so an approve retry can never double-order.
        details = {
            str(part["sku"]).strip(): (
                f"Qty {_fmt_qty(part.get('qty', 0))}"
                + (f" — {part['description']}" if part.get("description") else "")
            )
            for part in parts
        }
        client = document.get("client") or {}
        client_name = " ".join(
            str(client.get(field) or "").strip()
            for field in ("first_name", "last_name")
            if client.get(field)
        ).strip()
        where = client_name or "this job"
        title = f"Order parts — {quote.number}"
        body = f"{quote.number} for {where} was accepted. {len(parts)} SKUs to order."

        try:
            await notify_workspace_event(
                self.db,
                workspace_id=quote.workspace_id,
                notification_type="quote_accepted",
                title=title,
                body=body,
                data={"type": "quote_accepted", "quoteId": str(quote.id)},
                email_subject=title,
                email_heading="Parts to Order",
                email_intro=body,
                email_details=details,
                dedupe_key=f"quote_fulfillment:{quote.id}",
            )
        except Exception:
            self.log.exception(
                "quote_fulfillment_notify_failed",
                quote_id=str(quote.id),
                workspace_id=str(quote.workspace_id),
            )

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
        # Fixed or percentage — resolved through the shared deposit calculator so
        # the client page and the Stripe charge always agree on the amount due.
        from app.services.payments.quote_deposit_service import deposit_amount as resolve_amount

        deposit_due = resolve_amount(quote)
        deposit_paid = quote.deposit_paid_at is not None

        return PublicProposal(
            packages=self._public_packages(quote),
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
            deposit_amount=deposit_due,
            deposit_paid=deposit_paid,
            deposit_required=deposit_due is not None and not deposit_paid,
            # Allowlisted copy — the stored snapshot carries the staff-only
            # fulfillment sheet (distributor SKUs), which must not reach the
            # unauthenticated client page.
            proposal_document=client_safe_document(quote.proposal_document),
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

    def _public_packages(self, quote: Quote) -> list[PublicProposalPackage]:
        """Price every package this proposal offers the client to choose from.

        Each package's all-in total is derived through the same
        :func:`select_tier` path that builds the quote's own line items, and the
        deposit through the same calculator Stripe is charged from — so the
        number on the card is the number the client pays.

        Returns an empty list when there is nothing to choose (a plain quote, or
        a proposal with a single priced package).
        """
        raw = quote.proposal_document
        if not raw:
            return []
        try:
            document = ProposalDocument.model_validate(raw)
        except Exception:  # noqa: BLE001 - a malformed snapshot must not 500 the page
            self.log.warning("proposal_document_unreadable", quote_id=str(quote.id))
            return []
        keys = sellable_tier_keys(document)
        if len(keys) < 2:
            return []

        from app.services.payments.quote_deposit_service import deposit_for_total

        config = get_pricing_config(quote.workspace) if quote.workspace else None
        if config is None:
            return []
        by_key = {v.key: v for v in document.tiers}
        packages: list[PublicProposalPackage] = []
        for key in keys:
            view = by_key[key]
            selection = select_tier(
                tier_views=document.tiers,
                selected=key,
                charges=document.additional_charges,
                bistro=document.bistro,
                category_sections=document.category_sections,
                config=config,
            )
            packages.append(
                PublicProposalPackage(
                    key=key,
                    label=view.label,
                    name=view.name,
                    total=selection.grand_financed,
                    deposit_amount=deposit_for_total(quote, selection.grand_financed),
                    is_selected=key == document.selected_tier,
                )
            )
        return packages

    async def _apply_client_package(self, quote: Quote, tier_key: str) -> None:
        """Re-point a quote at the package the client chose, before approval.

        The client sends a package *key*; every line and every figure is
        re-derived server-side from the saved snapshot, so what they accept and
        what they're charged (deposit included) is the package they picked. A key
        that isn't a sellable package on this proposal is rejected.
        """
        raw = quote.proposal_document
        if not raw:
            raise ValidationError("This proposal has no packages to choose from.")
        try:
            document = ProposalDocument.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422, never a 500
            raise ValidationError("This proposal can no longer be changed.") from exc
        if tier_key == document.selected_tier:
            return
        config = get_pricing_config(quote.workspace) if quote.workspace else None
        if config is None:
            raise ValidationError("This proposal can no longer be changed.")
        catalog = await self._resolve_wizard_catalog(quote.workspace_id)
        try:
            updated, line_items = reselect_tier(document, tier_key, config=config, catalog=catalog)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        quote.line_items.clear()
        for item in line_items:
            quote.line_items.append(self._build_line_item(item))
        quote.proposal_document = updated.model_dump(mode="json")
        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info(
            "quote_package_selected_by_client",
            quote_id=str(quote.id),
            workspace_id=str(quote.workspace_id),
            selected_tier=tier_key,
            total=float(quote.total or 0),
        )

    async def approve_public(
        self, token: str, *, selected_tier: str | None = None
    ) -> PublicProposalActionResult:
        """Client approves their proposal via the public token (idempotent).

        When the client picked a package, the quote is re-pointed at it *before*
        approval so the approved quote, its line items, and the deposit Stripe
        charges all describe the package they actually chose.

        Reuses the operator approve path so the same lifecycle guards and
        automation event fire; an expired/declined proposal is rejected there.
        """
        quote = await self._load_by_token(token)
        # Re-pointing an already-decided quote would rewrite a signed agreement,
        # so the lifecycle guard runs first and a late package switch is ignored.
        if selected_tier and quote.status in {"draft", "sent"}:
            await self._apply_client_package(quote, selected_tier)
        result = await self.approve_quote(quote.workspace_id, quote.id)
        # Surface any unpaid deposit so the client page can hand off to checkout.
        from app.services.payments.quote_deposit_service import deposit_amount as resolve_amount

        due = resolve_amount(quote)
        unpaid = due is not None and quote.deposit_paid_at is None
        return PublicProposalActionResult(
            token=token,
            status=result.status,
            message="Thank you! Your proposal has been approved.",
            deposit_required=unpaid,
            deposit_amount=due,
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
        self._attach_deposit_to_document(document, payload, config)
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
        self._attach_deposit_to_document(document, payload, config)

        # Wizard quotes must carry a contact so an approved quote can convert into
        # a scheduled job. Use the explicit contact, else resolve/create one from
        # the collected client details (email then phone) within this workspace.
        await self._validate_refs(
            workspace_id,
            contact_id=payload.contact_id,
            service_location_id=payload.service_location_id,
            opportunity_id=payload.opportunity_id,
        )
        contact_id = payload.contact_id
        if contact_id is None:
            contact_id = await self._resolve_wizard_contact(workspace_id, payload)

        quote = Quote(
            workspace_id=workspace_id,
            contact_id=contact_id,
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
            quote.line_items.append(self._build_line_item(item))
        self._recompute_totals(quote)
        # Persist the resolved deposit selection onto the quote (one column only).
        selection = self._wizard_deposit_selection(payload, config)
        if selection is not None:
            mode, value = selection
            if mode == "fixed":
                quote.deposit_amount_fixed = round(value, 2)
            else:
                quote.deposit_percentage = min(100.0, round(value, 2))
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
    def _permanent_config_with_override(
        config: PricingSettings, per_ft_override: float | None
    ) -> PricingSettings:
        """Config copy with the permanent $/ft replaced by an internal override.

        Returns the config unchanged when no override is set. The copy is
        throwaway so the workspace's customer-facing pricing is never mutated.
        Shared by the live comparison and the estimate→quote conversion so both
        honor a rep's per-job rate identically.
        """
        if per_ft_override is None:
            return config
        return config.model_copy(
            update={"permanent": config.permanent.model_copy(update={"per_ft": per_ft_override})}
        )

    @staticmethod
    def _christmas_config_with_override(
        config: PricingSettings, roofline_override: float | None
    ) -> PricingSettings:
        """Config copy with the seasonal roofline $/ft replaced by an override."""
        if roofline_override is None:
            return config
        return config.model_copy(
            update={
                "christmas": config.christmas.model_copy(
                    update={"roofline_per_ft": roofline_override}
                )
            }
        )

    @staticmethod
    def _compute_comparison(
        config: PricingSettings, req: LinearFeetEstimateRequest
    ) -> LinearFeetEstimateResult:
        """Price permanent vs seasonal for a measured roofline (pure given config).

        Every dollar is computed server-side from the workspace pricing config; the
        rep's ``feet`` is the only untrusted input. Multi-year savings project the
        seasonal (temporary) cost over ``comparison_years`` seasons against
        permanent's one-time cost — the "pay once vs every season" pitch.

        Internal ``per_ft_override`` / ``christmas_per_ft_override`` (rep-only)
        adjust the permanent and seasonal linear-foot rates for this estimate via
        throwaway config copies, so the workspace's customer-facing pricing is
        never mutated. Each override affects only its own side.
        """
        perm_config = QuoteService._permanent_config_with_override(config, req.per_ft_override)
        xmas_config = QuoteService._christmas_config_with_override(
            config, req.christmas_per_ft_override
        )
        perm = price_permanent(perm_config, feet=req.feet, channels=req.channels)
        xmas = price_christmas(
            xmas_config,
            roofline_feet=req.feet,
            items=req.christmas_items,
            takedown=req.takedown,
            storage=req.storage,
        )
        # When the workspace sells Christmas as Good/Better/Best packages, price
        # every package from the same measurement so the rep tool can render tier
        # cards. The shared engine restricts each package to its covered decor
        # subset (+ roofline when included) and honors the seasonal per-ft override.
        christmas_packages = (
            price_christmas_packages(
                xmas_config,
                roofline_feet=req.feet,
                items=req.christmas_items,
                takedown=req.takedown,
                storage=req.storage,
            )
            if config.christmas.packages_enabled
            else []
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
                enabled=perm_enabled,
                total=perm_total,
                per_ft=float(perm.per_ft),
                roofline_cost=float(perm.roofline_cost) if perm_enabled else 0.0,
            ),
            christmas=ChristmasEstimate(
                enabled=xmas_enabled,
                total=xmas_total,
                per_ft=float(xmas_config.christmas.roofline_per_ft),
                roofline_cost=float(xmas.roofline_cost) if xmas_enabled else 0.0,
                items=list(xmas.items) if xmas_enabled else [],
            ),
            difference=difference,
            years=years,
            temporary_multi_year=temporary_multi_year,
            permanent_one_time=permanent_one_time,
            multi_year_savings=multi_year_savings,
            permanent_perks=list(config.permanent.perks),
            christmas_perks=list(config.christmas.perks),
            christmas_catalog=list(config.christmas.items),
            christmas_packages=christmas_packages,
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

    def _price_estimate_side(
        self, config: PricingSettings, req: EstimateQuoteRequest
    ) -> tuple[str, PermanentPricing | ChristmasPricing]:
        """Recompute the chosen side's priced breakdown for a quote.

        Returns ``(quote_title, pricing)``. The seasonal side prices the selected
        Good/Better/Best package when one is chosen and packages are enabled,
        else the à la carte roofline+decor. Raises :class:`ValidationError` when
        the requested side isn't enabled for the workspace, so the rep gets an
        actionable message instead of an empty quote.
        """
        if req.side == "permanent":
            if not config.permanent.enabled:
                raise ValidationError("Permanent lighting isn't enabled for this workspace.")
            perm_config = self._permanent_config_with_override(config, req.per_ft_override)
            pricing: PermanentPricing | ChristmasPricing = price_permanent(
                perm_config, feet=req.feet, channels=req.channels
            )
            return config.permanent.label, pricing

        if not config.christmas.enabled:
            raise ValidationError("Seasonal lighting isn't enabled for this workspace.")
        xmas_config = self._christmas_config_with_override(config, req.christmas_per_ft_override)
        if req.selected_package and config.christmas.packages_enabled:
            package = next(
                (p for p in config.christmas.packages if p.key == req.selected_package),
                None,
            )
            if package is not None:
                pricing = price_christmas_package(
                    xmas_config,
                    package,
                    roofline_feet=req.feet,
                    items=req.christmas_items,
                    takedown=req.takedown,
                    storage=req.storage,
                )
                return f"{config.christmas.label} — {package.name or package.label}", pricing
        pricing = price_christmas(
            xmas_config,
            roofline_feet=req.feet,
            items=req.christmas_items,
            takedown=req.takedown,
            storage=req.storage,
        )
        return config.christmas.label, pricing

    @staticmethod
    def _estimate_line_items(
        pricing: PermanentPricing | ChristmasPricing,
    ) -> list[QuoteLineItemCreate]:
        """Map a priced breakdown's display lines to quote line items.

        Each grossed ``CategoryLine`` becomes one quote line at ``quantity=1`` and
        ``unit_price=line_total`` — the authoritative cent-rounded component cost,
        with the measured feet/counts carried in the line label. This mirrors how
        the sales wizard emits permanent/seasonal sections, so the summed quote
        total matches the estimate exactly rather than drifting on per-unit
        rounding. When a job minimum lifted the priced total above the sum of
        components, a reconciling line keeps the quote total equal to that total.
        """
        items = [
            QuoteLineItemCreate(
                name=line.label,
                description=line.detail,
                quantity=1,
                unit_price=round(float(line.line_total), 2),
                discount=0,
            )
            for line in pricing.lines
            if line.line_total > 0
        ]
        shortfall = round(float(pricing.total) - float(pricing.raw_total), 2)
        if pricing.min_applied and shortfall > 0:
            items.append(
                QuoteLineItemCreate(
                    name="Job minimum", quantity=1, unit_price=shortfall, discount=0
                )
            )
        return items

    async def create_quote_from_estimate(
        self,
        workspace_id: uuid.UUID,
        req: EstimateQuoteRequest,
        *,
        created_by_id: int | None = None,
    ) -> QuoteDetailResponse:
        """Turn a measured roofline estimate into a real draft quote.

        The core of the light-designer tool: the drawn design's measurements price
        the chosen permanent or seasonal breakdown server-side, each grossed
        component becomes a quote line, and the client (when name/phone are given)
        is resolved onto a CRM contact with the same dedupe rules as the shared
        comparison. The quote is created as a draft through :meth:`create_quote`,
        so numbering, the workspace default deposit, total recomputation, and the
        client proposal link all apply unchanged.
        """
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        config = get_pricing_config(workspace)

        title, pricing = self._price_estimate_side(config, req)
        line_items = self._estimate_line_items(pricing)
        if not line_items:
            raise ValidationError("This estimate has nothing to quote yet — draw the design first.")

        first_name, last_name = _split_name(req.client_name)
        contact_id = await self._resolve_or_create_contact(
            workspace_id,
            first_name=first_name,
            last_name=last_name,
            email=req.client_email,
            phone=req.client_phone,
            source="roofline_estimator",
        )

        quote = await self.create_quote(
            workspace_id,
            QuoteCreate(
                contact_id=contact_id,
                title=req.label or title,
                currency="USD",
                line_items=line_items,
            ),
            created_by_id=created_by_id,
        )
        self.log.info(
            "quote_created_from_estimate",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            number=quote.number,
            side=req.side,
            contact_id=contact_id,
            total=float(quote.total),
        )
        return quote

    async def render_estimate(
        self,
        workspace_id: uuid.UUID,
        req: EstimateRenderRequest,
    ) -> EstimateRenderResult:
        """Render a drawn lighting design into a photorealistic night photo.

        Delegates to :func:`app.services.quotes.estimate_render.render_design`,
        which uses the workspace's OpenAI credential. Pure image transform — no
        pricing, no persistence. The design is the only data that leaves for
        OpenAI; every dollar stays server-computed.
        """
        from app.services.quotes.estimate_render import render_design

        await get_or_404(self.db, Workspace, workspace_id)
        image = await render_design(
            self.db,
            workspace_id,
            image=req.image,
            mode=req.mode,
            prompt=req.prompt,
        )
        return EstimateRenderResult(image=image)

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

        # Save onto a CRM customer when the rep supplied contact details. Splits
        # the free-text client name into first/last for a new contact; resolve/
        # dedupe rules match the sales wizard. Stays None (unlinked) otherwise.
        first_name, last_name = _split_name(req.client_name)
        contact_id = await self._resolve_or_create_contact(
            workspace_id,
            first_name=first_name,
            last_name=last_name,
            email=req.client_email,
            phone=req.client_phone,
            source="roofline_estimator",
        )

        comparison = RooflineComparison(
            workspace_id=workspace_id,
            feet=float(req.feet),
            channels=int(req.channels),
            takedown=bool(req.takedown),
            storage=bool(req.storage),
            per_ft_override=(
                float(req.per_ft_override) if req.per_ft_override is not None else None
            ),
            christmas_per_ft_override=(
                float(req.christmas_per_ft_override)
                if req.christmas_per_ft_override is not None
                else None
            ),
            christmas_items=req.christmas_items or None,
            selected_package=req.selected_package or None,
            client_name=req.client_name,
            label=req.label,
            contact_id=contact_id,
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
            contact_id=contact_id,
        )
        return ComparisonShareResult(
            token=comparison.public_token,
            url=url,
            contact_id=contact_id,
            saved_to_customer=contact_id is not None,
        )

    async def deliver_comparison(
        self,
        workspace_id: uuid.UUID,
        token: str,
        *,
        channel: str = "email",
        to: str | None = None,
    ) -> ComparisonDeliverResult:
        """Send a saved estimate's client link by ``email`` or ``sms``.

        Destination precedence: explicit ``to`` → the linked contact's email or
        phone. An estimate saved without a phone has no contact at all (contacts
        are phone-keyed), so both rails then need an explicit ``to``.

        Raises ``ValidationError`` when there's no destination, and
        ``NotFoundError`` for an unknown/other-workspace token.
        """
        from app.core.config import settings
        from app.services.email import send_estimate_email

        result = await self.db.execute(
            select(RooflineComparison)
            .where(
                RooflineComparison.public_token == token,
                RooflineComparison.workspace_id == workspace_id,
            )
            .options(
                selectinload(RooflineComparison.workspace),
                selectinload(RooflineComparison.contact),
            )
        )
        comparison = result.scalar_one_or_none()
        if comparison is None:
            raise NotFoundError("Comparison not found")

        workspace = comparison.workspace
        business = workspace.name if workspace else "our team"
        url = f"{settings.frontend_url.rstrip('/')}/p/compare/{comparison.public_token}"

        if channel not in ("email", "sms"):
            raise ValidationError(f"Unknown delivery channel: {channel!r}")

        if channel == "sms":
            phone = (to or "").strip() or (
                comparison.contact.phone_number if comparison.contact else None
            )
            if not phone:
                raise ValidationError(
                    "No customer phone for this estimate — add one or pass a destination."
                )
            first = (comparison.client_name or "").strip().split(" ")[0]
            greeting = f"Hi {first}, " if first else ""
            await self._text_client_link(
                workspace_id,
                phone=phone,
                contact_id=comparison.contact_id,
                body=(
                    f"{greeting}your lighting estimate from {business} is ready — "
                    f"take a look here: {url}"
                ),
                idempotency_scope="estimate_sms",
                idempotency_id=comparison.id,
            )
            self.log.info(
                "roofline_comparison_delivered",
                comparison_id=str(comparison.id),
                workspace_id=str(workspace_id),
                channel="sms",
            )
            return ComparisonDeliverResult(ok=True, channel="sms", to=phone)

        email_to = (to or "").strip() or (comparison.contact.email if comparison.contact else None)
        if not email_to:
            raise ValidationError(
                "No customer email for this estimate — add one or pass a destination."
            )

        sent = await send_estimate_email(
            to_email=email_to,
            workspace_name=business,
            estimate_url=url,
            client_name=comparison.client_name,
            idempotency_key=comparison.id,
        )
        if not sent:
            raise ValidationError("Could not send the estimate email. Please try again shortly.")

        self.log.info(
            "roofline_comparison_delivered",
            comparison_id=str(comparison.id),
            workspace_id=str(workspace_id),
            channel="email",
        )
        return ComparisonDeliverResult(ok=True, channel="email", to=email_to)

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
                per_ft_override=comparison.per_ft_override,
                christmas_per_ft_override=comparison.christmas_per_ft_override,
                christmas_items=comparison.christmas_items or {},
                selected_package=comparison.selected_package,
            ),
        )

        # Surface the full Good/Better/Best ladder to the client (feet-free) when
        # the workspace sells seasonal packages; otherwise the à la carte total
        # stands. The recommended package (rep's pick, else most-inclusive) drives
        # both the highlighted card and the single seasonal headline/savings
        # figure, so the comparison and the package grid always agree. Only the
        # total changes — the perks, difference, and multi-year projection keep
        # their current behavior.
        christmas_packages = build_public_comparison_packages(
            computed.christmas_packages, comparison.selected_package
        )
        recommended = _resolve_recommended_package(
            computed.christmas_packages, comparison.selected_package
        )
        christmas_total = (
            recommended.pricing.total if recommended is not None else computed.christmas.total
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
                enabled=computed.christmas.enabled, total=christmas_total
            ),
            difference=computed.difference,
            years=computed.years,
            temporary_multi_year=computed.temporary_multi_year,
            permanent_one_time=computed.permanent_one_time,
            multi_year_savings=computed.multi_year_savings,
            permanent_perks=computed.permanent_perks,
            christmas_perks=computed.christmas_perks,
            christmas_packages=christmas_packages,
            # Opt-in roofline-vs-roofline cost block; None keeps today's payload.
            roofline=build_public_roofline_comparison(config, computed),
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
        scheduled_start: datetime | None = None,
        scheduled_end: datetime | None = None,
    ) -> QuoteConvertResponse:
        """Convert an approved quote into a job and/or an invoice (idempotent).

        Re-running returns the already-linked job/invoice rather than creating
        duplicates. A job needs a ``contact_id``; converting to an invoice copies
        the quote's line items verbatim. When ``scheduled_start``/``scheduled_end``
        are supplied, the created job lands on the calendar as ``scheduled``.
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
            job_data: dict[str, object] = {
                "contact_id": quote.contact_id,
                "service_location_id": quote.service_location_id,
                "title": quote.title or f"Quote {quote.number}",
                "description": quote.notes,
                # Link the job to the just-created invoice (or a previously
                # converted one) so its P&L has a revenue side.
                "invoice_id": invoice_id,
                "technician_ids": [],
            }
            # An optional schedule window lands the job ``scheduled`` in one step
            # (JobService derives the status from the presence of the window).
            if scheduled_start is not None and scheduled_end is not None:
                job_data["scheduled_start"] = scheduled_start
                job_data["scheduled_end"] = scheduled_end
            job = await JobService(self.db).create(workspace_id, job_data)
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
        """Add a line item and recompute quote totals + attach metrics."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        categories = await self._catalog_categories(workspace_id, [item_in])
        quote.line_items.append(self._build_line_item(item_in, categories))
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
