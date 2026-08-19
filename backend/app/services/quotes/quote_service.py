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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.core.config import settings
from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Job, ServiceLocation
from app.models.human_nudge import HumanNudge
from app.models.lighting_project import LightingProject
from app.models.opportunity import Opportunity
from app.models.quote import Quote, QuoteLineItem, generate_quote_token
from app.models.roofline_comparison import RooflineComparison
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.attach_rules import AttachDismissal, AttachDismissalRequest, AttachWarning
from app.schemas.estimate import (
    ChristmasEstimate,
    ComparisonDeliverResult,
    ComparisonShareRequest,
    ComparisonShareResult,
    EstimateCustomLine,
    EstimateCustomLineCost,
    EstimateQuoteRequest,
    EstimateRenderRequest,
    EstimateRenderResult,
    LinearFeetEstimateRequest,
    LinearFeetEstimateResult,
    PermanentEstimate,
    PublicChristmasComparison,
    PublicComparison,
    PublicComparisonLine,
    PublicComparisonPackage,
    PublicPermanentComparison,
    PublicRooflineComparison,
)
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.schemas.pricing import (
    CategoryLine,
    ChristmasPackagePricing,
    ChristmasPricing,
    FinancingEstimate,
    PackagePricing,
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
    WizardCharge,
    WizardDepositSelection,
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
    QuoteServiceCreate,
    QuoteServiceResponse,
    QuoteUpdate,
)
from app.services.automations.events import (
    EVENT_QUOTE_APPROVED,
    EVENT_QUOTE_CONVERTED,
    EVENT_QUOTE_DECLINED,
    EVENT_QUOTE_SENT,
    emit_automation_event,
)
from app.services.email import send_quote_acceptance_receipt
from app.services.exceptions import ConflictError, NotFoundError, ValidationError
from app.services.idempotency import derive_outbound_key
from app.services.notifications import notify_workspace_event
from app.services.nudges.strategies.base import dedup_exists
from app.services.opportunities.quote_opportunity import (
    mark_quote_approved_on_pipeline,
    place_quote_on_pipeline,
)
from app.services.quotes.attach_metrics import compute_attach_metrics
from app.services.quotes.attach_rules import evaluate_attach_rules
from app.services.quotes.attach_rules_config import get_attach_rules_config
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.proposal_builder import (
    CatalogEntry,
    add_charge,
    build_proposal_document,
    remove_charge,
    reprice_document,
    reselect_tier,
    select_tier,
    sellable_tier_keys,
)
from app.services.quotes.proposal_pricing import (
    financing_estimate as build_financing_estimate,
)
from app.services.quotes.proposal_pricing import (
    price_christmas,
    price_christmas_package,
    price_christmas_packages,
    price_permanent,
)
from app.services.quotes.proposal_template import get_proposal_template
from app.services.quotes.quote_expiry import EXPIRED_STATUS, overdue_sent_predicate
from app.services.recurring_jobs.service_plan_provisioner import ServicePlanProvisioner
from app.services.workspaces.membership import assert_active_workspace_member

logger = structlog.get_logger()

WIZARD_INPUT_VERSION = 1


# Generic over the concrete package type (bound to the presentation contract) so
# a caller gets its own type back — seasonal in, seasonal out — rather than a
# widened protocol it would have to narrow again to read a breakdown.
def _resolve_recommended_package[PackageT: PackagePricing](
    packages: Sequence[PackageT],
    selected_key: str | None,
) -> PackageT | None:
    """The package to steer the client toward, for any service category.

    Precedence — unchanged for seasonal lighting:

    1. The rep's explicit pick, when it names a priced package.
    2. A tier the operator flagged ``recommended``: how a good/better/best ladder
       anchors on its middle option instead of its most expensive one. Seasonal
       packages never set this (:attr:`ChristmasPackagePricing.recommended` is a
       constant ``False``), so they fall straight through to (3) exactly as they
       always have.
    3. The most-inclusive tier — last in ``package_order``, which both
       :func:`price_christmas_packages` and :func:`price_service_packages` emit
       low→high.

    Mirrors the frontend ``resolveSelectedPackage``. ``None`` when the workspace
    sells no packages.
    """
    if not packages:
        return None
    if selected_key:
        for pkg in packages:
            if pkg.key == selected_key:
                return pkg
    for pkg in packages:
        if pkg.recommended:
            return pkg
    return packages[-1]


def build_public_comparison_packages(
    packages: Sequence[PackagePricing],
    selected_key: str | None,
) -> list[PublicComparisonPackage]:
    """Map priced packages of any category to the measurement-free public cards.

    Only each package's ``total`` crosses the public boundary — never the pricing
    breakdown behind it (seasonal carries ``roofline_feet`` / ``roofline_cost``,
    a service tier carries its measured ``units``), so a measurement cannot leak
    to the homeowner. :class:`~app.schemas.pricing.PackagePricing` is what makes
    that structural rather than a habit: the protocol exposes ``total`` and no
    other money, so there is no breakdown in scope here to leak by accident.

    The recommended tier is flagged for a highlight, not a gate.
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
            # Seasonal packages report ``{"roofline": bool}``; a category with no
            # roofline reports nothing and the flag stays at its default False,
            # which is what the public card has always meant by "no roofline".
            includes_roofline=pkg.includes.get("roofline", False),
            total=pkg.total,
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

# How long one client "visit" lasts for view-tracking purposes. Beacons arriving
# inside this window of ``last_viewed_at`` are a no-op: they neither bump the
# timestamp nor increment the count. Reading a proposal is not a single page
# load -- people refresh, switch packages, and reopen the tab -- so an
# unthrottled counter turns one interested customer into "40 views" and the
# number stops carrying information. It also caps the write rate on an
# unauthenticated endpoint at one UPDATE per quote per window, regardless of how
# much traffic the link attracts.
VIEW_THROTTLE_MINUTES = 15


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
        tenant's contact and have the platform echo decrypted details.
        """
        if contact_id is not None:
            await assert_workspace_owned(
                self.db, Contact, contact_id, workspace_id, detail="Contact not found"
            )
        if service_location_id is not None:
            location = await assert_workspace_owned(
                self.db,
                ServiceLocation,
                service_location_id,
                workspace_id,
                detail="Service location not found",
            )
            if contact_id is not None and location.contact_id != contact_id:
                raise ValidationError("Service location does not belong to the selected contact")
        if opportunity_id is not None:
            opportunity = await assert_workspace_owned(
                self.db,
                Opportunity,
                opportunity_id,
                workspace_id,
                detail="Opportunity not found",
            )
            if (
                contact_id is not None
                and opportunity.primary_contact_id is not None
                and opportunity.primary_contact_id != contact_id
            ):
                raise ValidationError("Opportunity does not belong to the selected contact")

    async def _validated_lighting_project(
        self,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
        *,
        contact_id: int,
        service_location_id: uuid.UUID | None,
        opportunity_id: uuid.UUID | None,
    ) -> LightingProject:
        project = await assert_workspace_owned(
            self.db,
            LightingProject,
            project_id,
            workspace_id,
            detail="Lighting project not found",
        )
        if project.status != "active" or project.contact_id != contact_id:
            raise ValidationError("Lighting project does not belong to the selected contact")
        if service_location_id is not None and project.service_location_id != service_location_id:
            raise ValidationError(
                "Lighting project does not belong to the selected service location"
            )
        if opportunity_id is not None and project.opportunity_id != opportunity_id:
            raise ValidationError("Lighting project does not belong to the selected opportunity")
        if project.installation_shot_id is None:
            raise ValidationError("Select and save an installation sheet before creating a quote")
        from app.schemas.lighting_project import LandscapeDraftDocument

        document = LandscapeDraftDocument.model_validate(project.document)
        if project.installation_shot_id not in {shot.id for shot in document.shots}:
            raise ValidationError("Selected installation sheet is missing from the project")
        return project

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
    def _quote_category_totals(  # noqa: PLR0912 - handles three persisted quote shapes
        quote: Quote,
    ) -> dict[str, float]:
        """Return positive service subtotals used only for financing eligibility.

        Core quotes carry categories on their line items. Wizard quotes predate
        that snapshot and instead carry product-line keys in ``proposal_document``;
        list reads may have neither relationship loaded, so ``primary_service`` is
        the final (single-category) fallback. No branch changes the quote's price.
        """

        def amount(raw: object) -> float:
            try:
                return max(0.0, float(raw or 0))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 0.0

        totals: dict[str, float] = {}
        loaded_lines = quote.__dict__.get("line_items")
        if loaded_lines is not None:
            for line in loaded_lines:
                category = str(line.service_category or "").strip().lower()
                line_amount = amount(line.total)
                if category and line_amount > 0:
                    totals[category] = totals.get(category, 0.0) + line_amount
        if totals:
            return totals

        document = quote.proposal_document if isinstance(quote.proposal_document, dict) else {}
        raw_categories = document.get("categories", [])
        categories = (
            [str(category).strip().lower() for category in raw_categories if str(category).strip()]
            if isinstance(raw_categories, list)
            else []
        )
        raw_sections = document.get("category_sections", [])
        for section in raw_sections if isinstance(raw_sections, list) else []:
            if not isinstance(section, dict):
                continue
            category = str(section.get("key") or "").strip().lower()
            section_amount = amount(section.get("financed_total"))
            if category and section_amount > 0:
                totals[category] = section_amount

        if "landscape" in categories:
            selected = document.get("selected_tier")
            raw_tiers = document.get("tiers", [])
            for tier in raw_tiers if isinstance(raw_tiers, list) else []:
                if not isinstance(tier, dict) or tier.get("key") != selected:
                    continue
                pricing = tier.get("pricing")
                tier_amount = amount(pricing.get("base")) if isinstance(pricing, dict) else 0
                if tier_amount > 0:
                    totals["landscape"] = tier_amount
                break
        bistro = document.get("bistro")
        if "bistro" in categories and isinstance(bistro, dict):
            bistro_amount = amount(bistro.get("total"))
            if bistro_amount > 0:
                totals["bistro"] = bistro_amount
        if totals:
            return totals

        total = amount(quote.total)
        if categories and total > 0:
            return dict.fromkeys(categories, total)
        primary = str(quote.primary_service or "").strip().lower()
        return {primary: total} if primary and total > 0 else {}

    @classmethod
    def _financing_for_quote(
        cls, quote: Quote, config: PricingSettings
    ) -> FinancingEstimate | None:
        """Build the non-contractual payment estimate exposed by quote APIs."""
        return build_financing_estimate(
            float(quote.total or 0), cls._quote_category_totals(quote), config
        )

    async def _pricing_config_for_quote(self, quote: Quote) -> PricingSettings:
        """Return the pricing config behind this quote's financing block.

        Prefers an already-loaded ``workspace`` relationship, then reads through
        the session's identity map, so decorating a response never costs a
        second round trip for a workspace the caller already holds.

        A missing workspace falls back to defaults rather than raising. This
        runs *after* writes like ``approve_quote`` have committed, so turning a
        settled approval into a 404 would report a failure that did not happen
        — and it matches ``get_pricing_config``'s own never-500-a-read contract.
        """
        workspace = quote.__dict__.get("workspace")
        if not isinstance(workspace, Workspace):
            workspace = await self.db.get(Workspace, quote.workspace_id)
        if not isinstance(workspace, Workspace):
            logger.warning(
                "quote_pricing_config_workspace_missing",
                quote_id=str(quote.id),
                workspace_id=str(quote.workspace_id),
            )
            return PricingSettings()
        return get_pricing_config(workspace)

    @classmethod
    def _decorate_wizard_edit_state(cls, response: QuoteResponse, quote: Quote) -> None:
        response.is_wizard_quote = quote.proposal_document is not None
        if response.is_wizard_quote:
            response.wizard_edit_mode = (
                "revise" if cls._wizard_quote_requires_revision(quote) else "update"
            )

    async def _detail_response(self, quote: Quote) -> QuoteDetailResponse:
        if "assignee" not in quote.__dict__:
            await self.db.refresh(quote, ["assignee"])
        response = QuoteDetailResponse.model_validate(quote)
        self._decorate_wizard_edit_state(response, quote)
        config = await self._pricing_config_for_quote(quote)
        response.financing = self._financing_for_quote(quote, config)
        response.services = self._services_for(quote)
        return response

    def _services_for(self, quote: Quote) -> list[QuoteServiceResponse]:
        """Project this quote's operator-addable services into one shape.

        Which persistence answers depends on how the quote was built. A wizard
        quote's line items are *derived* from its snapshot and are rebuilt from
        scratch whenever the document is repriced, so its editable services are
        the document's add-on charges. A plain quote has no document and its line
        items are the truth, so they are the services.

        A snapshot that no longer parses returns nothing rather than raising:
        this runs on every quote read, and one bad document must not 500 a list.
        """
        raw = quote.proposal_document
        if not raw:
            return [
                QuoteServiceResponse(
                    id=str(li.id),
                    name=li.name,
                    description=li.description,
                    amount=float(li.total or 0),
                )
                for li in quote.line_items
            ]
        try:
            document = ProposalDocument.model_validate(raw)
        except Exception:  # noqa: BLE001 - a malformed snapshot must not 500 a read
            self.log.warning("proposal_document_unreadable", quote_id=str(quote.id))
            return []
        return [
            QuoteServiceResponse(
                id=str(charge.id),
                name=charge.description,
                amount=float(charge.amount),
            )
            for charge in document.additional_charges
            # A charge with no id predates the addressable-charge migration and
            # cannot be targeted for removal; omitting it is honest, whereas
            # listing an un-deletable row is a button that does nothing.
            if charge.id
        ]

    @classmethod
    def _summary_response(cls, quote: Quote, config: PricingSettings) -> QuoteResponse:
        response = QuoteResponse.model_validate(quote)
        cls._decorate_wizard_edit_state(response, quote)
        response.financing = cls._financing_for_quote(quote, config)
        return response

    @staticmethod
    def _line_total(quantity: float, unit_price: float, discount: float) -> float:
        return round(quantity * unit_price - discount, 2)

    def _apply_attach_rules(
        self,
        quote: Quote,
        workspace: Workspace,
        dismissal: AttachDismissalRequest | None,
    ) -> AttachWarning | None:
        """Enforce the workspace's attach rules on a quote about to be saved.

        The cross-sell prompt: a roof job with no gutters on it is the single
        biggest lever on average job value, and it only works if it fires while
        the rep can still act on it. Returns the advisory warning to hand back on
        the response, or ``None`` when there is nothing to say.

        Called *before* the insert so a ``blocking`` rule genuinely rejects the
        save rather than persisting a quote and complaining afterwards. Raises
        :class:`ValidationError` (a 400 carrying the structured warning in
        ``details``) in exactly two cases:

        * a ``blocking`` rule matched and no dismissal was supplied;
        * a dismissal was supplied without a reason while the workspace requires
          one — in *any* mode, because a reason-less dismissal is not reportable
          and an unreportable dismissal is the thing this feature exists to fix.

        A dismissal for a quote that earned no warning is ignored rather than
        recorded: the rep may have added the attach after the prompt appeared,
        and inventing a "they declined" event for a quote that has the attach
        would poison the very report it feeds.

        Requires ``quote.line_items`` to be loaded and ``_recompute_totals`` to
        have run (it derives ``primary_service``).
        """
        config = get_attach_rules_config(workspace)
        warning = evaluate_attach_rules(
            config,
            primary_service=quote.primary_service,
            present_categories=[li.service_category for li in quote.line_items],
        )
        if warning is None:
            return None

        if dismissal is None:
            if warning.mode == "blocking":
                raise ValidationError(
                    f"{warning.message} Add one of: "
                    f"{', '.join(warning.suggested_categories)} — or dismiss with a reason.",
                    details=warning.model_dump(mode="json"),
                )
            return warning

        reason = (dismissal.reason or "").strip() or None
        if reason is None and config.require_dismissal_reason:
            raise ValidationError(
                "Choose a reason for skipping the add-on before saving.",
                details=warning.model_dump(mode="json"),
            )

        # Reassign rather than append: SQLAlchemy does not track in-place
        # mutation of a plain JSONB list, so an appended dismissal would be
        # silently dropped on flush.
        quote.attach_dismissals = [
            *(quote.attach_dismissals or []),
            AttachDismissal(
                primary_service=warning.primary_service,
                categories=list(warning.suggested_categories),
                reason=reason,
                dismissed_at=datetime.now(UTC),
            ).model_dump(mode="json"),
        ]
        self.log.info(
            "quote_attach_dismissed",
            workspace_id=str(quote.workspace_id),
            primary_service=warning.primary_service,
            categories=warning.suggested_categories,
            mode=warning.mode,
        )
        return None

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

    async def _default_assignee_id(
        self,
        workspace_id: uuid.UUID,
        *,
        opportunity_id: uuid.UUID | None,
        created_by_id: int | None,
    ) -> int | None:
        """Prefer an active linked-deal owner, then the active quote creator."""
        if opportunity_id is not None:
            owner_result = await self.db.execute(
                select(Opportunity.assigned_user_id)
                .join(User, User.id == Opportunity.assigned_user_id)
                .join(
                    WorkspaceMembership,
                    (WorkspaceMembership.user_id == User.id)
                    & (WorkspaceMembership.workspace_id == Opportunity.workspace_id),
                )
                .where(
                    Opportunity.id == opportunity_id,
                    Opportunity.workspace_id == workspace_id,
                    User.is_active.is_(True),
                )
            )
            owner_id = owner_result.scalar_one_or_none()
            if owner_id is not None:
                return owner_id

        if created_by_id is None:
            return None
        creator_result = await self.db.execute(
            select(User.id)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .where(
                User.id == created_by_id,
                User.is_active.is_(True),
                WorkspaceMembership.workspace_id == workspace_id,
            )
        )
        return creator_result.scalar_one_or_none()

    async def _expire_overdue(self, workspace_id: uuid.UUID) -> None:
        """Flip still-``sent`` quotes past their ``expiry_date`` to ``expired``.

        One scoped UPDATE keeps reads truthful without a background worker; it is
        idempotent and a no-op when nothing has lapsed.
        """
        await self.db.execute(
            update(Quote)
            .where(
                Quote.workspace_id == workspace_id,
                overdue_sent_predicate(),
            )
            .values(status=EXPIRED_STATUS)
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
        assigned_user_id: int | None = None,
    ) -> PaginatedQuotes:
        """List a workspace's quotes, newest first, with optional filters."""
        await self._expire_overdue(workspace_id)

        query = (
            select(Quote)
            .where(Quote.workspace_id == workspace_id)
            .options(selectinload(Quote.assignee))
        )
        if status:
            query = query.where(Quote.status == status)
        if contact_id is not None:
            query = query.where(Quote.contact_id == contact_id)
        if assigned_user_id is not None:
            query = query.where(Quote.assigned_user_id == assigned_user_id)
        query = query.order_by(Quote.created_at.desc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        config = get_pricing_config(workspace)
        items = [self._summary_response(quote, config) for quote in result.items]
        return PaginatedQuotes(**result.to_dict(items))

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
        assigned_user_id = await self._default_assignee_id(
            workspace_id,
            opportunity_id=quote_in.opportunity_id,
            created_by_id=created_by_id,
        )
        quote = Quote(
            workspace_id=workspace_id,
            contact_id=quote_in.contact_id,
            service_location_id=quote_in.service_location_id,
            opportunity_id=quote_in.opportunity_id,
            assigned_user_id=assigned_user_id,
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
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        # Inherit the workspace's default deposit when the operator set none.
        if quote.deposit_percentage is None and quote.deposit_amount_fixed is None:
            self._apply_default_deposit(quote, workspace)
        categories = await self._catalog_categories(workspace_id, quote_in.line_items)
        for item in quote_in.line_items:
            quote.line_items.append(self._build_line_item(item, categories))

        self._recompute_totals(quote)
        # Before the insert: a blocking attach rule must reject the save, not
        # persist a quote and then complain about it.
        attach_warning = self._apply_attach_rules(quote, workspace, quote_in.attach_dismissal)
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
        response = await self._detail_response(quote)
        response.attach_warning = attach_warning
        return response

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
            options=[selectinload(Quote.line_items), selectinload(Quote.assignee)],
        )
        return await self._detail_response(quote)

    async def update_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        quote_in: QuoteUpdate,
    ) -> QuoteDetailResponse:
        """Update mutable quote headers and keep wizard hydration metadata aligned."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)

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
        stored_input = self._stored_proposal_input(quote)
        if stored_input is not None:
            deposit = None
            if quote.deposit_amount_fixed is not None:
                deposit = WizardDepositSelection(
                    mode="fixed", value=float(quote.deposit_amount_fixed)
                )
            elif quote.deposit_percentage is not None:
                deposit = WizardDepositSelection(
                    mode="percentage", value=float(quote.deposit_percentage)
                )
            stored_input = stored_input.model_copy(
                update={
                    "contact_id": quote.contact_id,
                    "service_location_id": quote.service_location_id,
                    "opportunity_id": quote.opportunity_id,
                    "title": quote.title,
                    "notes": quote.notes,
                    "terms": quote.terms,
                    "deposit": deposit,
                }
            )
            quote.proposal_input = stored_input.model_dump(
                mode="json", exclude={"attach_dismissal"}
            )
        if quote_in.model_fields_set:
            quote.proposal_version += 1
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return await self._detail_response(quote)

    async def assign_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        assigned_user_id: int | None,
    ) -> QuoteDetailResponse:
        """Reassign or clear sales ownership, including on locked quotes."""
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items), selectinload(Quote.assignee)],
        )
        assignee = None
        if assigned_user_id is not None:
            assignee = await assert_active_workspace_member(self.db, workspace_id, assigned_user_id)
        quote.assigned_user_id = assigned_user_id
        quote.assignee = assignee
        await self.db.commit()
        return await self._detail_response(quote)

    async def delete_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> None:
        """Delete only an unprotected draft/sent quote with no revision descendants."""
        quote = await get_or_404(self.db, Quote, quote_id, workspace_id=workspace_id)
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot delete a {quote.status} quote")
        if (
            quote.deposit_paid_at is not None
            or quote.deposit_checkout_session_id is not None
            or quote.deposit_payment_intent_id is not None
            or quote.converted_job_id is not None
            or quote.converted_invoice_id is not None
        ):
            raise ConflictError("Cannot delete a quote with payment or conversion history")
        descendant_id = await self.db.scalar(
            select(Quote.id)
            .where(
                Quote.workspace_id == workspace_id,
                (Quote.revision_of_quote_id == quote_id)
                | (Quote.revision_root_quote_id == quote_id),
            )
            .limit(1)
        )
        if descendant_id is not None:
            raise ConflictError("Cannot delete a quote that anchors a revision history")
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

        # Deliberately ignoring the result: "mark sent" is a status change an
        # operator makes after sending by their own means, and the courtesy
        # email riding along must not fail the transition. ``deliver`` is the
        # path that promises delivery, and that one does check.
        await self._email_quote(quote)
        return await self._detail_response(quote)

    async def prepare_for_in_person_approval(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Publish a proposal for review on the operator's device without sending it.

        This performs the same lifecycle transition and token allocation as delivery,
        but deliberately sends no email or SMS. It is the narrow path used when the
        customer is physically present and will review the public proposal on the
        technician's phone or tablet.
        """
        quote = await self._load_for_send(workspace_id, quote_id)
        await self._ensure_sent_state(quote)
        return await self._detail_response(quote)

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

        First send is also when the price-validity clock starts: a quote with no
        explicit ``expiry_date`` gets the workspace's
        ``pricing.quote_validity_days`` window from today. Anchoring on send
        rather than creation means a draft that sits for a fortnight still
        reaches the customer with the full window, and re-sending never quietly
        extends a deadline the customer has already been shown.
        """
        if quote.status in {"approved", "declined"}:
            raise ConflictError(f"Cannot send a {quote.status} quote")
        if quote.sent_at is None:
            quote.sent_at = datetime.now(UTC)
        if quote.expiry_date is None:
            workspace = await get_or_404(self.db, Workspace, quote.workspace_id)
            validity = get_pricing_config(workspace).quote_validity_days
            quote.expiry_date = quote.sent_at.date() + timedelta(days=validity)
        if quote.public_token is None:
            quote.public_token = generate_quote_token()
        already_sent = quote.status == "sent"
        quote.status = "sent"
        if not already_sent:
            await self._emit_lifecycle_event(quote, EVENT_QUOTE_SENT)
            await self._place_on_pipeline(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

    async def _place_on_pipeline(self, quote: Quote) -> None:
        """Put the quoted contact on the sales board (first send only).

        Runs inside the send transaction so a card can never outlive a send that
        rolled back. Best-effort: a pipeline hiccup must not stop the quote from
        reaching the customer, which is the operator's actual intent.
        """
        if quote.contact_id is None:
            return
        try:
            contact = await self.db.get(Contact, quote.contact_id)
            if contact is None:
                return
            opportunity = await place_quote_on_pipeline(
                self.db,
                quote.workspace_id,
                contact,
                quote_id=quote.id,
            )
            if opportunity is not None and quote.opportunity_id is None:
                quote.opportunity_id = opportunity.id
        except Exception as exc:  # noqa: BLE001 — never block a send on the board
            self.log.warning(
                "quote_pipeline_placement_failed",
                quote_id=str(quote.id),
                error=str(exc),
            )

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
            # An operator who clicked "Email quote" is telling the customer it
            # is on its way. Reporting ok on a send Resend never accepted means
            # the quote sits unread while the dashboard says delivered — the
            # failure surfaces days later as "they never got back to me". The
            # SMS rail below already raises when its rail isn't ready; this
            # matches it.
            if not await self._email_quote(
                quote,
                override_email=email_to,
                delivery_attempt_id=uuid.uuid4(),
            ):
                raise ValidationError(
                    "Couldn't send that email — the quote is saved and still marked sent, "
                    "so you can retry or copy the client link instead."
                )
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

        Thin delegate to :func:`app.services.messaging.client_sms.send_client_link_sms`,
        which invoices share, so proposal and invoice texts honour identical
        rails (Telnyx configured, opt-out respected, SMS-capable sender).
        """
        from app.services.messaging.client_sms import send_client_link_sms

        await send_client_link_sms(
            self.db,
            workspace_id,
            phone=phone,
            contact_id=contact_id,
            body=body,
            idempotency_scope=idempotency_scope,
            idempotency_id=idempotency_id,
        )

    async def approve_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        expected_proposal_version: int | None = None,
    ) -> QuoteDetailResponse:
        """Approve once while serializing against any customer-facing edit."""
        await self._expire_overdue(workspace_id)
        result = await self.db.execute(
            select(Quote)
            .where(Quote.id == quote_id, Quote.workspace_id == workspace_id)
            .options(selectinload(Quote.line_items))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        quote = result.scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found")
        if (
            expected_proposal_version is not None
            and quote.proposal_version != expected_proposal_version
        ):
            raise ConflictError(
                "This proposal changed after you opened it. Refresh and review the new terms.",
                code="proposal_changed",
            )
        if quote.status == "approved":
            return await self._detail_response(quote)
        if expected_proposal_version is not None and quote.status != "sent":
            raise ConflictError(
                "This proposal is no longer awaiting customer approval",
                code="proposal_not_approvable",
            )
        if quote.status not in {"draft", "sent"}:
            raise ConflictError(f"Cannot approve a {quote.status} quote")
        quote.status = "approved"
        quote.approved_at = datetime.now(UTC)
        await mark_quote_approved_on_pipeline(self.db, workspace_id, quote)
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
        return await self._detail_response(quote)

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
            return await self._detail_response(quote)
        if quote.status not in {"draft", "sent"}:
            raise ConflictError(f"Cannot decline a {quote.status} quote")
        quote.status = "declined"
        quote.declined_at = datetime.now(UTC)
        quote.decline_reason = reason
        await self._emit_lifecycle_event(quote, EVENT_QUOTE_DECLINED)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info("quote_declined", quote_id=str(quote.id), workspace_id=str(workspace_id))
        return await self._detail_response(quote)

    async def _email_quote(
        self,
        quote: Quote,
        *,
        override_email: str | None = None,
        delivery_attempt_id: uuid.UUID | None = None,
    ) -> bool:
        """Email the quote's proposal link. Never raises; reports whether it sent.

        Destination: explicit override → wizard snapshot's client email → the
        linked contact's email. Wizard proposals usually have no Contact row,
        so the snapshot fallback is what makes their sends actually deliver.

        An explicit delivery gets a fresh ``delivery_attempt_id`` so clicking
        "Re-send email" creates a new provider message. The best-effort courtesy
        email attached to ``mark_sent`` omits it and remains revision-idempotent.

        Returns ``True`` only when Resend accepted the message. The caller
        decides what a ``False`` means: emailing a quote *on purpose* has to
        surface the failure, while the email tacked onto ``mark_sent`` is a side
        effect that must not undo the status change.
        """
        from app.core.config import settings
        from app.services.email import send_quote_email
        from app.services.idempotency import derive_document_send_key

        client = (quote.proposal_document or {}).get("client") or {}
        contact_email = (
            (override_email or "").strip()
            or (client.get("email") or "").strip()
            or (quote.contact.email if quote.contact else None)
        )
        if not contact_email:
            self.log.info("quote_email_skipped_no_contact", quote_id=str(quote.id))
            return False

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
            return await send_quote_email(
                to_email=contact_email,
                workspace_name=workspace_name,
                quote_number=quote.number,
                amount_str=amount_str,
                title=quote.title,
                expiry_date=expiry,
                notes=quote.notes,
                proposal_url=proposal_url,
                # Explicit deliveries are intentional attempts, including the
                # "Re-send email" action, and must create a new provider message.
                # The courtesy email on mark_sent stays revision-idempotent so a
                # retried status transition cannot duplicate it.
                idempotency_key=(
                    derive_outbound_key(
                        "quote_delivery",
                        quote.id,
                        delivery_attempt_id,
                        contact_email,
                    )
                    if delivery_attempt_id is not None
                    else derive_document_send_key(
                        "quote_send", quote.id, quote.updated_at, contact_email
                    )
                ),
            )
        except Exception as exc:  # pragma: no cover - best-effort email
            self.log.warning("quote_email_failed", quote_id=str(quote.id), error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Public client proposal (no auth, token-keyed)
    # ------------------------------------------------------------------

    async def _load_by_token(self, token: str, *, for_update: bool = False) -> Quote:
        """Load a sent quote by its public token, or raise ``NotFoundError``.

        Drafts have no token and never resolve; an unknown token 404s. Expiry is
        applied lazily so a lapsed proposal reads (and behaves) truthfully.
        """
        statement = (
            select(Quote)
            .where(Quote.public_token == token)
            .options(
                selectinload(Quote.line_items),
                selectinload(Quote.contact),
                selectinload(Quote.workspace),
            )
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        result = await self.db.execute(statement)
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
        pricing_config = get_pricing_config(quote.workspace)
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
            proposal_version=quote.proposal_version or 1,
            currency=quote.currency,
            subtotal=float(quote.subtotal or 0),
            tax_amount=float(quote.tax_amount or 0),
            discount_amount=float(quote.discount_amount or 0),
            total=total,
            financing=self._financing_for_quote(quote, pricing_config),
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

        await self._persist_repriced_document(quote, updated, line_items, increment_version=False)
        self.log.info(
            "quote_package_selected_by_client",
            quote_id=str(quote.id),
            workspace_id=str(quote.workspace_id),
            selected_tier=tier_key,
            total=float(quote.total or 0),
        )

    async def _persist_repriced_document(
        self,
        quote: Quote,
        document: ProposalDocument,
        line_items: list[QuoteLineItemCreate],
        *,
        increment_version: bool = True,
    ) -> None:
        """Write a repriced snapshot and the lines it derives, as one commit.

        Every line is replaced rather than diffed, because on a wizard quote the
        line items are output, not state: the document is the only thing that is
        edited, and rebuilding from it is what guarantees the two cannot drift.
        This is also why a service added to such a quote has to live on the
        document — a line item written directly here would be erased the next
        time anything repriced.
        """
        quote.line_items.clear()
        categories = await self._catalog_categories(quote.workspace_id, line_items)
        for item in line_items:
            quote.line_items.append(self._build_line_item(item, categories))
        quote.proposal_document = document.model_dump(mode="json")
        self._recompute_totals(quote)
        if increment_version:
            quote.proposal_version += 1
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

    # ------------------------------------------------------------------
    # Services (post-save adds)
    # ------------------------------------------------------------------

    async def add_service(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        payload: QuoteServiceCreate,
    ) -> QuoteDetailResponse:
        """Add one service to an existing quote, whichever shape it is.

        The caller names a service and an amount; where that lands is this
        method's problem. A wizard quote gets a document add-on charge and is
        repriced from the document, so the service reaches the client proposal,
        raises every package total, and survives the client switching packages. A
        plain quote gets a line item, which is where its money already lives.
        """
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        before = float(quote.total or 0)
        wizard = bool(quote.proposal_document)

        if wizard:
            document = self._parse_document(quote)
            config = await self._config_for_edit(quote)
            try:
                updated, service_id = add_charge(
                    document,
                    description=payload.name,
                    net_amount=payload.amount,
                    config=config,
                    catalog_item_id=payload.catalog_item_id,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            stored_input = self._stored_proposal_input(quote)
            if stored_input is not None:
                stored_input = stored_input.model_copy(
                    update={
                        "additional_charges": [
                            *stored_input.additional_charges,
                            WizardCharge(
                                description=payload.name,
                                net_amount=payload.amount,
                                catalog_item_id=payload.catalog_item_id,
                            ),
                        ]
                    }
                )
                quote.proposal_input = stored_input.model_dump(
                    mode="json", exclude={"attach_dismissal"}
                )
            catalog = await self._resolve_wizard_catalog(workspace_id)
            repriced, line_items = reprice_document(updated, config=config, catalog=catalog)
            await self._persist_repriced_document(quote, repriced, line_items)
        else:
            item = QuoteLineItemCreate(
                name=payload.name,
                quantity=1,
                unit_price=payload.amount,
                catalog_item_id=payload.catalog_item_id,
            )
            categories = await self._catalog_categories(workspace_id, [item])
            line = self._build_line_item(item, categories)
            quote.line_items.append(line)
            self._recompute_totals(quote)
            await self.db.commit()
            await self.db.refresh(quote, ["line_items"])
            service_id = str(line.id)

        self.log.info(
            "quote_service_added",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            service_id=service_id,
            wizard=wizard,
            total_before=before,
            total_after=float(quote.total or 0),
        )
        return await self._detail_response(quote)

    async def remove_service(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        service_id: str,
    ) -> QuoteDetailResponse:
        """Remove a previously added service, mirroring :meth:`add_service`."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        before = float(quote.total or 0)

        if quote.proposal_document:
            document = self._parse_document(quote)
            charge_index = next(
                (
                    index
                    for index, charge in enumerate(document.additional_charges)
                    if charge.id == service_id
                ),
                None,
            )
            config = await self._config_for_edit(quote)
            try:
                updated = remove_charge(document, service_id)
            except ValueError as exc:
                raise NotFoundError(str(exc)) from exc
            stored_input = self._stored_proposal_input(quote)
            if stored_input is not None and charge_index is not None:
                charges = list(stored_input.additional_charges)
                if charge_index < len(charges):
                    charges.pop(charge_index)
                    stored_input = stored_input.model_copy(update={"additional_charges": charges})
                    quote.proposal_input = stored_input.model_dump(
                        mode="json", exclude={"attach_dismissal"}
                    )
            catalog = await self._resolve_wizard_catalog(workspace_id)
            repriced, line_items = reprice_document(updated, config=config, catalog=catalog)
            await self._persist_repriced_document(quote, repriced, line_items)
        else:
            try:
                line_id = uuid.UUID(service_id)
            except ValueError as exc:
                raise NotFoundError("That service is no longer on this quote") from exc
            line = next((li for li in quote.line_items if li.id == line_id), None)
            if line is None:
                raise NotFoundError("That service is no longer on this quote")
            quote.line_items.remove(line)
            await self.db.delete(line)
            self._recompute_totals(quote)
            await self.db.commit()
            await self.db.refresh(quote, ["line_items"])

        self.log.info(
            "quote_service_removed",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            service_id=service_id,
            total_before=before,
            total_after=float(quote.total or 0),
        )
        return await self._detail_response(quote)

    def _stored_proposal_input(self, quote: Quote) -> ProposalWizardPayload | None:
        """Parse optional hydration state without breaking unrelated basic edits."""
        if quote.proposal_input is None:
            return None
        try:
            return ProposalWizardPayload.model_validate(quote.proposal_input)
        except ValueError:
            self.log.warning(
                "quote_proposal_input_invalid",
                quote_id=str(quote.id),
                proposal_input_version=quote.proposal_input_version,
            )
            return None

    def _parse_document(self, quote: Quote) -> ProposalDocument:
        """Parse a quote's snapshot, as a 422 rather than a 500 when it is bad."""
        try:
            return ProposalDocument.model_validate(quote.proposal_document)
        except Exception as exc:  # noqa: BLE001 - surfaced as a 422, never a 500
            raise ValidationError("This quote can no longer be changed.") from exc

    async def _config_for_edit(self, quote: Quote) -> PricingSettings:
        """Pricing config for repricing a snapshot, or a 422 when unavailable.

        Deliberately *not* :meth:`_pricing_config_for_quote`, which falls back to
        default :class:`PricingSettings` for a missing workspace. That is right
        for decorating a read, and wrong here: this config sets the finance
        buffer every line on the document is grossed up by, so defaulting it
        would quietly reprice the customer's whole quote off the wrong numbers.
        Refusing the edit leaves the quote exactly as the rep last saw it.
        """
        workspace = quote.__dict__.get("workspace")
        if not isinstance(workspace, Workspace):
            workspace = await self.db.get(Workspace, quote.workspace_id)
        if not isinstance(workspace, Workspace):
            self.log.warning(
                "quote_service_edit_workspace_missing",
                quote_id=str(quote.id),
                workspace_id=str(quote.workspace_id),
            )
            raise ValidationError("This quote can no longer be changed.")
        return get_pricing_config(workspace)

    async def approve_public(
        self,
        token: str,
        *,
        proposal_version: int | None,
        selected_tier: str | None = None,
    ) -> PublicProposalActionResult:
        """Client approves their proposal via the public token (idempotent).

        When the client picked a package, the quote is re-pointed at it *before*
        approval so the approved quote, its line items, and the deposit Stripe
        charges all describe the package they actually chose.

        Reuses the operator approve path so the same lifecycle guards and
        automation event fire; an expired/declined proposal is rejected there.
        """
        quote = await self._load_by_token(token, for_update=True)
        expected_version = proposal_version
        if expected_version is None:
            # Keep deployment order backward-compatible without weakening edited
            # quotes: the prior frontend omitted this field, and only an untouched
            # version-1 proposal is guaranteed to still match what it rendered.
            if quote.proposal_version != 1:
                raise ConflictError(
                    "This proposal changed after you opened it. Refresh and review the new terms.",
                    code="proposal_version_required",
                )
            expected_version = 1
        if quote.proposal_version != expected_version:
            raise ConflictError(
                "This proposal changed after you opened it. Refresh and review the new terms.",
                code="proposal_changed",
            )
        should_send_receipt = quote.status == "sent"
        # Re-pointing an already-decided quote would rewrite a signed agreement,
        # so the lifecycle guard runs first and a late package switch is ignored.
        if selected_tier and quote.status in {"draft", "sent"}:
            await self._apply_client_package(quote, selected_tier)
        result = await self.approve_quote(
            quote.workspace_id,
            quote.id,
            expected_proposal_version=expected_version,
        )
        # Surface any unpaid deposit so the client page can hand off to checkout.
        from app.services.payments.quote_deposit_service import deposit_amount as resolve_amount

        due = resolve_amount(quote)
        unpaid = due is not None and quote.deposit_paid_at is None
        if should_send_receipt:
            await self._send_acceptance_receipt(quote, deposit_amount=due)
        return PublicProposalActionResult(
            token=token,
            status=result.status,
            message="Thank you! Your proposal has been approved.",
            deposit_required=unpaid,
            deposit_amount=due,
        )

    async def _send_acceptance_receipt(self, quote: Quote, *, deposit_amount: float | None) -> None:
        """Best-effort transactional receipt for the customer who accepted."""
        contact = quote.contact
        workspace = quote.workspace
        if contact is None or not contact.email:
            return
        try:
            await send_quote_acceptance_receipt(
                to_email=contact.email,
                customer_name=contact.first_name or contact.full_name or "there",
                business_name=workspace.name,
                quote_number=quote.number,
                quote_title=quote.title or f"Proposal {quote.number}",
                total=float(quote.total),
                currency=quote.currency,
                accepted_at=quote.approved_at or datetime.now(UTC),
                idempotency_key=derive_outbound_key("quote_acceptance_receipt", quote.id),
                support_email=str(workspace.settings.get("support_email") or "") or None,
                support_phone=str(workspace.settings.get("support_phone") or "") or None,
                deposit_required=deposit_amount is not None,
                deposit_amount=deposit_amount,
                deposit_paid=quote.deposit_paid_at is not None,
                proposal_url=f"{settings.frontend_url.rstrip('/')}/p/quotes/{quote.public_token}",
            )
        except Exception as exc:  # pragma: no cover - best-effort receipt
            self.log.warning(
                "quote_acceptance_receipt_failed",
                quote_id=str(quote.id),
                error=str(exc),
            )

    async def record_public_view(self, token: str) -> None:
        """Record that a client opened their proposal, and alert the operator once.

        Called from an explicit ``POST /{token}/view`` beacon rather than from
        the GET, so reading a proposal stays a pure, cacheable read and there is
        exactly one narrow write surface on the unauthenticated path.

        **Why this signal is trustworthy.** The public proposal page is a client
        component: the beacon only fires from a browser that executed JavaScript.
        The link scanners that plague email read-receipts (Outlook Safe Links,
        Gmail's image proxy, Apple Mail Privacy Protection) fetch the Next.js
        route, get an HTML shell, and never reach this endpoint. A recorded view
        is a human.

        Repeat beacons within :data:`VIEW_THROTTLE_MINUTES` of ``last_viewed_at``
        return without writing -- see that constant for why an unthrottled count
        is worse than no count. ``first_viewed_at`` is stamped once and never
        overwritten, so "they finally opened it" survives every re-read.

        An unknown or draft token raises ``NotFoundError`` from ``_load_by_token``
        before anything is written.
        """
        quote = await self._load_by_token(token)
        now = datetime.now(UTC)

        last = quote.last_viewed_at
        if last is not None:
            # Defensive: a naive timestamp would raise on subtraction, and a 500
            # on an unauthenticated beacon is worse than a slightly early bump.
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if now - last < timedelta(minutes=VIEW_THROTTLE_MINUTES):
                return

        is_first_view = quote.first_viewed_at is None
        if is_first_view:
            quote.first_viewed_at = now
        quote.last_viewed_at = now
        quote.view_count = (quote.view_count or 0) + 1

        if is_first_view:
            await self._nudge_quote_viewed(quote, now)

        await self.db.commit()
        self.log.info(
            "quote_viewed_by_client",
            quote_id=str(quote.id),
            workspace_id=str(quote.workspace_id),
            view_count=quote.view_count,
            first_view=is_first_view,
        )

    async def _nudge_quote_viewed(self, quote: Quote, now: datetime) -> None:
        """Queue the "call them while they're still reading it" operator nudge.

        Created inline rather than by a polling strategy so the dashboard's nudge
        list reflects it within its own 60s poll -- the fast path that makes the
        alert actionable. SMS/push still ride the hourly
        :class:`~app.workers.nudge_worker.NudgeWorker` pass, deliberately: an
        inline send would let anyone holding a public link trigger outbound spend.

        ``dedup_key`` is per quote, not per view, so re-reads never produce a
        second alert.

        The insert is ``ON CONFLICT DO NOTHING`` rather than a read-then-add.
        Unlike the polling nudge strategies -- which run single-threaded in a
        worker, so a check-then-insert is safe there -- this runs on a public
        endpoint with arbitrary concurrency: two tabs opened at once would both
        pass a pre-check and the second INSERT would raise on the unique index,
        turning ordinary customer behaviour into a 500 and losing that request's
        view increment. Letting Postgres arbitrate makes the race a no-op.
        """
        dedup_key = f"{quote.id}:quote_viewed"
        if await dedup_exists(self.db, dedup_key):
            return

        client_name: str | None = None
        if quote.contact is not None:
            client_name = quote.contact.full_name or quote.contact.first_name
        who = client_name or "Your client"

        await self.db.execute(
            pg_insert(HumanNudge)
            .values(
                id=uuid.uuid4(),
                workspace_id=quote.workspace_id,
                contact_id=quote.contact_id,
                nudge_type="quote_viewed",
                title=f"\U0001f440 {who} opened quote {quote.number}",
                message=(
                    f"\U0001f440 {who} just opened proposal {quote.number}. "
                    "They're thinking about it right now -- call while it is "
                    "still on their screen."
                ),
                suggested_action="call",
                priority="high",
                due_date=now,
                status="pending",
                dedup_key=dedup_key,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["dedup_key"])
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
                catalog_item_id=item.id,
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

        The attach prompt is evaluated here too, through the same line-item
        categorization the save path uses, so preview and save can never disagree
        about whether a quote is missing its add-on. Surfacing it *during* the
        build is what makes the prompt actionable: the rep can add the gutters,
        or dismiss it with a reason that is recorded on the quote as it is
        created, instead of hearing about it only once a quote already exists.
        """
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        config = get_pricing_config(workspace)
        catalog = await self._resolve_wizard_catalog(workspace_id)
        document, line_items = build_proposal_document(config, catalog, payload)
        self._attach_deposit_to_document(document, payload, config)
        document.attach_warning = await self._preview_attach_warning(
            workspace, workspace_id, line_items
        )
        return document

    async def _preview_attach_warning(
        self,
        workspace: Workspace,
        workspace_id: uuid.UUID,
        line_items: Sequence[QuoteLineItemCreate],
    ) -> AttachWarning | None:
        """Evaluate the attach rules against an unsaved wizard selection.

        Builds throwaway line items with exactly the categorization the save path
        applies, so the previewed prompt is the prompt the save would raise. This
        is advisory only — the rule is *enforced* in
        :meth:`_apply_attach_rules` on save, so a client that ignores the preview
        still cannot slip a blocking rule.
        """
        categories = await self._catalog_categories(workspace_id, line_items)
        lines = [self._build_line_item(item, categories) for item in line_items]
        primary, _, _ = compute_attach_metrics(lines)
        return evaluate_attach_rules(
            get_attach_rules_config(workspace),
            primary_service=primary,
            present_categories=[line.service_category for line in lines],
        )

    @staticmethod
    def _wizard_quote_requires_revision(quote: Quote) -> bool:
        """Return whether repricing must preserve ``quote`` as an audit record.

        A decided or converted quote is already a customer-approved/accounting
        record. Any payment provider id also freezes the quote: an unpaid Stripe
        Checkout Session still names an amount, so changing that amount in place
        could let the old session settle against different proposal terms.
        """
        return (
            quote.status not in {"draft", "sent"}
            or quote.deposit_paid_at is not None
            or quote.deposit_checkout_session_id is not None
            or quote.deposit_payment_intent_id is not None
            or quote.converted_job_id is not None
            or quote.converted_invoice_id is not None
        )

    async def _wizard_quote_for_write(self, workspace_id: uuid.UUID, quote_id: uuid.UUID) -> Quote:
        result = await self.db.execute(
            select(Quote)
            .where(Quote.id == quote_id, Quote.workspace_id == workspace_id)
            .options(selectinload(Quote.line_items))
            .with_for_update()
        )
        quote = result.scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found")
        if quote.proposal_document is None:
            raise ConflictError(
                "Only a sales-wizard quote can be reopened in the quote builder",
                code="wizard_quote_required",
            )
        return quote

    async def _apply_wizard_payload(
        self,
        quote: Quote,
        workspace: Workspace,
        payload: ProposalWizardPayload,
    ) -> tuple[ProposalDocument, AttachWarning | None]:
        """Rebuild every customer-facing price from one trusted wizard input."""
        workspace_id = workspace.id
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

        lighting_project_id = None
        if payload.lighting_project_id is not None:
            if contact_id is None:
                raise ValidationError("A lighting project quote requires a linked contact")
            lighting_project = await self._validated_lighting_project(
                workspace_id,
                payload.lighting_project_id,
                contact_id=contact_id,
                service_location_id=payload.service_location_id,
                opportunity_id=payload.opportunity_id,
            )
            lighting_project_id = lighting_project.id

        quote.contact_id = contact_id
        quote.service_location_id = payload.service_location_id
        quote.opportunity_id = payload.opportunity_id
        quote.lighting_project_id = lighting_project_id
        quote.title = payload.title or self._wizard_title(document)
        quote.notes = payload.notes
        quote.terms = payload.terms
        quote.currency = "USD"
        quote.tax_amount = 0
        quote.discount_amount = 0
        quote.proposal_document = document.model_dump(mode="json")
        stored_payload = payload.model_copy(update={"contact_id": contact_id, "title": quote.title})
        quote.proposal_input = stored_payload.model_dump(mode="json", exclude={"attach_dismissal"})
        quote.proposal_input_version = WIZARD_INPUT_VERSION

        # Replacing the relationship lets delete-orphan remove stale priced lines
        # in the same transaction; no old price can survive a wizard reprice.
        categories = await self._catalog_categories(workspace_id, line_items)
        quote.line_items = [self._build_line_item(item, categories) for item in line_items]
        self._recompute_totals(quote)

        # Re-resolve the deposit after the total, clearing whichever old mode was
        # present first so percentage and fixed values can never coexist.
        quote.deposit_percentage = None
        quote.deposit_amount_fixed = None
        selection = self._wizard_deposit_selection(payload, config)
        if selection is not None:
            mode, value = selection
            if mode == "fixed":
                quote.deposit_amount_fixed = round(value, 2)
            else:
                quote.deposit_percentage = min(100.0, round(value, 2))

        attach_warning = self._apply_attach_rules(quote, workspace, payload.attach_dismissal)
        return document, attach_warning

    async def save_from_wizard(
        self,
        workspace_id: uuid.UUID,
        payload: ProposalWizardPayload,
        *,
        created_by_id: int | None = None,
    ) -> QuoteDetailResponse:
        """Persist a new server-priced wizard proposal as a draft quote."""
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        assigned_user_id = await self._default_assignee_id(
            workspace_id,
            opportunity_id=payload.opportunity_id,
            created_by_id=created_by_id,
        )
        quote = Quote(
            workspace_id=workspace_id,
            assigned_user_id=assigned_user_id,
            number=await self._next_quote_number(workspace_id),
            status="draft",
            created_by_id=created_by_id,
        )
        document, attach_warning = await self._apply_wizard_payload(quote, workspace, payload)
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
        response = await self._detail_response(quote)
        response.attach_warning = attach_warning
        return response

    async def update_from_wizard(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        payload: ProposalWizardPayload,
    ) -> QuoteDetailResponse:
        """Reopen an unpaid draft/sent quote in place, preserving its public token."""
        quote = await self._wizard_quote_for_write(workspace_id, quote_id)
        if self._wizard_quote_requires_revision(quote):
            raise ConflictError(
                "This quote is protected; create a revision instead",
                code="quote_revision_required",
                details={"quote_id": str(quote.id), "recommended_action": "revise"},
            )
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        document, attach_warning = await self._apply_wizard_payload(quote, workspace, payload)
        # Keep a sent proposal live at the same URL. Its monotonic version makes a
        # customer approval rendered before this commit fail safely instead of
        # accepting the new prices sight unseen.
        quote.proposal_version += 1
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info(
            "quote_updated_from_wizard",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            status=quote.status,
            selected_tier=document.selected_tier,
        )
        response = await self._detail_response(quote)
        response.attach_warning = attach_warning
        return response

    async def revise_from_wizard(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        payload: ProposalWizardPayload,
        *,
        created_by_id: int | None = None,
    ) -> QuoteDetailResponse:
        """Copy a protected wizard quote into a separately numbered draft."""
        source = await self._wizard_quote_for_write(workspace_id, quote_id)
        if not self._wizard_quote_requires_revision(source):
            raise ConflictError(
                "This quote can still be updated in place",
                code="quote_update_allowed",
                details={"quote_id": str(source.id), "recommended_action": "update"},
            )
        workspace = await get_or_404(self.db, Workspace, workspace_id)
        revision = Quote(
            workspace_id=workspace_id,
            assigned_user_id=source.assigned_user_id,
            number=await self._next_quote_number(workspace_id),
            status="draft",
            issue_date=date.today(),
            revision_of_quote_id=source.id,
            revision_root_quote_id=source.revision_root_quote_id or source.id,
            revision_number=source.revision_number + 1,
            created_by_id=created_by_id,
        )
        document, attach_warning = await self._apply_wizard_payload(revision, workspace, payload)
        self.db.add(revision)
        await self.db.commit()
        await self.db.refresh(revision, ["line_items"])
        self.log.info(
            "quote_revised_from_wizard",
            source_quote_id=str(source.id),
            revision_quote_id=str(revision.id),
            workspace_id=str(workspace_id),
            selected_tier=document.selected_tier,
        )
        response = await self._detail_response(revision)
        response.attach_warning = attach_warning
        return response

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
    def _price_custom_lines(
        lines: Sequence[EstimateCustomLine], side: str, *, package_key: str | None = None
    ) -> list[EstimateCustomLineCost]:
        """Price one bucket of standalone lines: quantity × unit price, cent-rounded.

        No gross-up. Every other figure on an estimate starts as a *net* rate the
        engine marks up; a standalone line is the rep typing the client-facing
        amount directly, so marking it up again would quietly overcharge the
        number they just quoted out loud in the driveway.

        ``package_key`` selects the bucket, and the match is exact both ways:
        ``None`` returns only the global lines (today's behavior), a key returns
        only the lines pinned to that tier. Nothing is ever counted twice, and a
        line naming a package the caller never asks about simply doesn't appear —
        which is what drops a line whose key matches no priced package.
        """
        return [
            EstimateCustomLineCost(
                **line.model_dump(),
                amount=round(float(line.quantity) * float(line.unit_price), 2),
            )
            for line in lines
            if line.side == side and line.package_key == package_key
        ]

    @staticmethod
    def _with_custom_lines[PricingT: PermanentPricing | ChristmasPricing](
        pricing: PricingT, lines: Sequence[EstimateCustomLineCost]
    ) -> PricingT:
        """Fold priced standalone lines into a side's breakdown and its total.

        ``raw_total`` and ``total`` move together, so ``total - raw_total`` (the
        job-minimum shortfall :meth:`_estimate_line_items` reconciles) is
        untouched: an add-on tops up a job that already met the minimum instead
        of being swallowed by it. The lines land at the end of the breakdown,
        which is where they read on a quote.

        A multiple carries into the label ("3 × Bucket truck day") the way decor
        labels carry their feet, because :meth:`_estimate_line_items` emits every
        line at quantity 1 priced at its authoritative total — so without this
        the count would be lost on the way to the quote.
        """
        if not lines:
            return pricing
        subtotal = round(sum(line.amount for line in lines), 2)
        # ``model_copy`` returns the same concrete model; mypy widens it to the
        # TypeVar's bound, so the cast restores what the caller passed in.
        return cast(
            "PricingT",
            pricing.model_copy(
                update={
                    "lines": [
                        *pricing.lines,
                        *(
                            CategoryLine(
                                label=(
                                    line.label
                                    if line.quantity == 1
                                    else f"{line.quantity:g} × {line.label}"
                                ),
                                detail=line.description,
                                quantity=line.quantity,
                                unit_price=line.unit_price,
                                line_total=line.amount,
                            )
                            for line in lines
                        ),
                    ],
                    "raw_total": round(float(pricing.raw_total) + subtotal, 2),
                    "total": round(float(pricing.total) + subtotal, 2),
                }
            ),
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

        Standalone ``custom_lines`` are added to the side they name, after the
        engine has priced that side. A global line (no ``package_key``) is
        intentionally left *out* of the package ladder, so a tier card still
        quotes its own scope; a tier-scoped line is folded into exactly that
        card's total and kept out of ``custom_total``, which the client page adds
        *on top of* a package total — double-counting is the one real hazard
        here. Neither kind touches either ``roofline_cost``, so the
        roofline-vs-roofline block stays a like-for-like comparison of the same
        run of lights.
        """
        perm_config = QuoteService._permanent_config_with_override(config, req.per_ft_override)
        xmas_config = QuoteService._christmas_config_with_override(
            config, req.christmas_per_ft_override
        )
        # Global lines only: a tier-scoped line belongs to one card, and folding
        # it in here too would bill it twice on the page the homeowner opens.
        perm_custom = QuoteService._price_custom_lines(req.custom_lines, "permanent")
        xmas_custom = QuoteService._price_custom_lines(req.custom_lines, "seasonal")
        perm = QuoteService._with_custom_lines(
            price_permanent(
                perm_config,
                feet=req.feet,
                channels=req.channels,
                complexity=req.permanent_complexity,
                complexity_feet=req.permanent_complexity_feet,
            ),
            perm_custom,
        )
        xmas = QuoteService._with_custom_lines(
            price_christmas(
                xmas_config,
                roofline_feet=req.feet,
                items=req.christmas_items,
                takedown=req.takedown,
                storage=req.storage,
            ),
            xmas_custom,
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
        # A line pinned to a tier is priced inside that tier's own card, so it
        # follows the package it was sold with when the rep switches tiers. Keyed
        # by package so the scoped lines can also be echoed on ``custom_lines``
        # for the rep panel; a key matching no priced package is never visited
        # here, which is exactly how an unknown key gets dropped.
        scoped_custom: dict[str, list[EstimateCustomLineCost]] = {}
        priced_packages: list[ChristmasPackagePricing] = []
        for pkg in christmas_packages:
            scoped = QuoteService._price_custom_lines(
                req.custom_lines, "seasonal", package_key=pkg.key
            )
            scoped_custom[pkg.key] = scoped
            priced_packages.append(
                pkg.model_copy(
                    update={"pricing": QuoteService._with_custom_lines(pkg.pricing, scoped)}
                )
                if scoped
                else pkg
            )
        christmas_packages = priced_packages
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
                package_feet=perm.package_feet if perm_enabled else 0,
                package_cogs=perm.package_cogs if perm_enabled else 0.0,
                markup=perm.markup if perm_enabled else 0.0,
                per_ft=0,
                roofline_cost=float(perm.roofline_cost) if perm_enabled else 0.0,
                custom_total=(
                    round(sum(line.amount for line in perm_custom), 2) if perm_enabled else 0.0
                ),
            ),
            christmas=ChristmasEstimate(
                enabled=xmas_enabled,
                total=xmas_total,
                per_ft=float(xmas_config.christmas.roofline_per_ft),
                roofline_cost=float(xmas.roofline_cost) if xmas_enabled else 0.0,
                custom_total=(
                    round(sum(line.amount for line in xmas_custom), 2) if xmas_enabled else 0.0
                ),
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
            # Grouped by side (request order within each), then the tier-scoped
            # seasonal lines in package order — each already inside its own card's
            # total, and carrying its ``package_key`` so the rep panel can read it
            # under that card. Lines belonging to a service this workspace doesn't
            # sell, or naming a package it doesn't price, are dropped rather than
            # shown against a total they were never added to.
            custom_lines=[
                *(
                    line
                    for line in (*perm_custom, *xmas_custom)
                    if (line.side == "permanent" and perm_enabled)
                    or (line.side == "seasonal" and xmas_enabled)
                ),
                *(
                    line
                    for pkg in christmas_packages
                    for line in scoped_custom.get(pkg.key, [])
                    if xmas_enabled
                ),
            ],
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
        else the à la carte roofline+decor. The rep's standalone lines for that
        side are appended either way, so an add-on the customer agreed to on the
        estimate becomes a real line on the quote instead of evaporating at
        conversion. A line scoped to a package joins them only on that package's
        quote — folded exactly once, alongside the global lines — and is dropped
        on any other tier, because it was priced into that card and no other.
        Raises :class:`ValidationError` when the requested side isn't enabled for
        the workspace, so the rep gets an actionable message instead of an empty
        quote.
        """
        custom = self._price_custom_lines(req.custom_lines, req.side)
        if req.side == "permanent":
            if not config.permanent.enabled:
                raise ValidationError("Permanent lighting isn't enabled for this workspace.")
            perm_config = self._permanent_config_with_override(config, req.per_ft_override)
            pricing: PermanentPricing | ChristmasPricing = self._with_custom_lines(
                price_permanent(
                    perm_config,
                    feet=req.feet,
                    channels=req.channels,
                    complexity=req.permanent_complexity,
                ),
                custom,
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
                pricing = self._with_custom_lines(
                    price_christmas_package(
                        xmas_config,
                        package,
                        roofline_feet=req.feet,
                        items=req.christmas_items,
                        takedown=req.takedown,
                        storage=req.storage,
                    ),
                    [
                        *custom,
                        *self._price_custom_lines(
                            req.custom_lines, req.side, package_key=package.key
                        ),
                    ],
                )
                return f"{config.christmas.label} — {package.name or package.label}", pricing
        pricing = self._with_custom_lines(
            price_christmas(
                xmas_config,
                roofline_feet=req.feet,
                items=req.christmas_items,
                takedown=req.takedown,
                storage=req.storage,
            ),
            custom,
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
            # Stored as inputs, like every other field here: the amounts are
            # recomputed on each public view so a fixed typo shows up on the link
            # the client already has.
            custom_lines=[line.model_dump() for line in req.custom_lines] or None,
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
                custom_lines=[
                    EstimateCustomLine.model_validate(line)
                    for line in (comparison.custom_lines or [])
                ],
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
        # A package total covers that package's scope plus any line scoped to it,
        # so only the *global* standalone lines are added back here — without this
        # the client's headline would quietly drop every add-on the moment
        # packages are on, and with a scoped line counted twice it would overbill.
        # ``custom_total`` is global-only by construction, which is what keeps
        # this addition safe.
        christmas_total = (
            round(recommended.pricing.total + computed.christmas.custom_total, 2)
            if recommended is not None
            else computed.christmas.total
        )
        # The client sees the add-ons on the price they're actually being quoted:
        # the global lines plus the ones scoped to the recommended tier. Lines
        # scoped to a tier they aren't being sold are already inside a different
        # card's total and would only confuse the itemization here.
        recommended_key = recommended.key if recommended is not None else None
        client_lines = [
            line
            for line in computed.custom_lines
            if line.package_key is None or line.package_key == recommended_key
        ]

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
            # Itemized so the client sees what the add-ons on their price are.
            custom_lines=[
                PublicComparisonLine(
                    label=line.label,
                    description=line.description,
                    quantity=line.quantity,
                    amount=line.amount,
                    side=line.side,
                )
                for line in client_lines
            ],
        )

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    async def convert_quote(  # noqa: PLR0912, PLR0915
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        create_job: bool = True,
        create_invoice: bool = True,
        scheduled_start: datetime | None = None,
        scheduled_end: datetime | None = None,
        crew_id: uuid.UUID | None = None,
        technician_ids: Sequence[uuid.UUID] = (),
        confirm_unpaid_deposit: bool = False,
    ) -> QuoteConvertResponse:
        """Atomically convert one approved quote, with exact-retry semantics."""
        from app.services.invoices import InvoiceService
        from app.services.jobs import JobService
        from app.services.payments.quote_deposit_service import deposit_amount

        if (scheduled_start is None) != (scheduled_end is None):
            raise ValidationError("scheduled_start and scheduled_end must be provided together")
        if (
            scheduled_start is not None
            and scheduled_end is not None
            and scheduled_end <= scheduled_start
        ):
            raise ValidationError("scheduled_end must be after scheduled_start")
        if not create_job and (crew_id is not None or technician_ids):
            raise ValidationError("An installation team requires job creation")

        quote_result = await self.db.execute(
            select(Quote)
            .where(Quote.id == quote_id, Quote.workspace_id == workspace_id)
            .options(selectinload(Quote.line_items))
            .with_for_update()
        )
        quote = quote_result.scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found")
        if quote.status != "approved":
            raise ConflictError("Only an approved quote can be converted")
        if create_job and (scheduled_start is None or scheduled_end is None):
            raise ValidationError("A complete schedule window is required to create a job")

        if quote.lighting_project_id is not None:
            project = await self._validated_lighting_project(
                workspace_id,
                quote.lighting_project_id,
                contact_id=cast(int, quote.contact_id),
                service_location_id=quote.service_location_id,
                opportunity_id=quote.opportunity_id,
            )
            if project.installation_shot_id is None:
                raise ConflictError("The linked project no longer has an installation sheet")

        deposit_due = deposit_amount(quote)
        if (
            create_job
            and deposit_due is not None
            and quote.deposit_paid_at is None
            and not confirm_unpaid_deposit
        ):
            raise ConflictError(
                "Required deposit is unpaid; confirm before scheduling",
                code="unpaid_deposit_confirmation_required",
                details={"deposit_amount": deposit_due},
            )

        requested_technicians = tuple(dict.fromkeys(technician_ids))
        existing_job = None
        if quote.converted_job_id is not None:
            existing_job = await self.db.scalar(
                select(Job)
                .where(
                    Job.id == quote.converted_job_id,
                    Job.workspace_id == workspace_id,
                )
                .options(selectinload(Job.technicians))
            )
        if existing_job is None:
            existing_job = await self.db.scalar(
                select(Job)
                .where(
                    Job.source_quote_id == quote.id,
                    Job.workspace_id == workspace_id,
                )
                .options(selectinload(Job.technicians))
            )

        requested_flags_conflict = (not create_job and existing_job is not None) or (
            not create_invoice and quote.converted_invoice_id is not None
        )
        if existing_job is not None:
            existing_technicians = {technician.id for technician in existing_job.technicians}
            exact_job_retry = (
                create_job
                and existing_job.scheduled_start == scheduled_start
                and existing_job.scheduled_end == scheduled_end
                and existing_job.crew_id == crew_id
                and existing_technicians == set(requested_technicians)
            )
            if not exact_job_retry or requested_flags_conflict:
                raise ConflictError("Quote was already converted with different handoff details")
        elif quote.converted_job_id is not None or requested_flags_conflict:
            raise ConflictError("Quote conversion links no longer match the requested handoff")

        if quote.converted_invoice_id is not None and not create_invoice:
            raise ConflictError("Quote was already converted with different create flags")

        idempotent_replay = existing_job is not None or quote.converted_invoice_id is not None
        job_id = existing_job.id if existing_job is not None else quote.converted_job_id
        invoice_id = quote.converted_invoice_id
        created_something = False
        try:
            if create_invoice and invoice_id is None:
                paid_deposit = (
                    float(deposit_due or 0.0) if quote.deposit_paid_at is not None else 0.0
                )
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
                                name=line.name,
                                description=line.description,
                                quantity=float(line.quantity),
                                unit_price=float(line.unit_price),
                                discount=float(line.discount),
                            )
                            for line in quote.line_items
                        ],
                    ),
                    created_by_id=quote.created_by_id,
                    amount_paid=paid_deposit,
                    payment_intent_id=(quote.deposit_payment_intent_id if paid_deposit else None),
                    commit=False,
                )
                invoice_id = invoice.id
                quote.converted_invoice_id = invoice_id
                created_something = True

            if create_job and existing_job is None:
                if quote.contact_id is None:
                    raise ConflictError("Cannot create a job from a quote with no contact")
                job = await JobService(self.db).create(
                    workspace_id,
                    {
                        "contact_id": quote.contact_id,
                        "service_location_id": quote.service_location_id,
                        "crew_id": crew_id,
                        "title": quote.title or f"Quote {quote.number}",
                        "description": quote.notes,
                        "invoice_id": invoice_id,
                        "source_quote_id": quote.id,
                        "lighting_project_id": quote.lighting_project_id,
                        "technician_ids": list(requested_technicians),
                        "scheduled_start": scheduled_start,
                        "scheduled_end": scheduled_end,
                    },
                )
                job_id = job.id
                quote.converted_job_id = job_id
                created_something = True

            if created_something:
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
        except IntegrityError as error:
            await self.db.rollback()
            if "uq_field_service_jobs_source_quote" in str(error):
                raise ConflictError("Quote conversion raced; retry the exact handoff") from error
            raise

        await self.db.refresh(quote, ["line_items"])
        self.log.info(
            "quote_converted",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            job_id=str(job_id) if job_id else None,
            invoice_id=str(invoice_id) if invoice_id else None,
            idempotent_replay=idempotent_replay and not created_something,
        )
        return QuoteConvertResponse(
            quote=await self._detail_response(quote),
            job_id=job_id,
            invoice_id=invoice_id,
            idempotent_replay=idempotent_replay and not created_something,
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
        quote.proposal_version += 1
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return await self._detail_response(quote)

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
        quote.proposal_version += 1
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return await self._detail_response(quote)

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
        quote.proposal_version += 1
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return await self._detail_response(quote)

    async def _get_mutable_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> Quote:
        """Lock and load a quote whose customer/payment terms may still change."""
        result = await self.db.execute(
            select(Quote)
            .where(Quote.id == quote_id, Quote.workspace_id == workspace_id)
            .options(selectinload(Quote.line_items))
            .with_for_update()
        )
        quote = result.scalar_one_or_none()
        if quote is None:
            # Preserve the established tenant-safe 404 shape used by every quote
            # mutation while the successful path still gets a database row lock.
            await get_or_404(self.db, Quote, quote_id, workspace_id=workspace_id)
            raise NotFoundError("Quote not found")
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"This quote is {quote.status} and can no longer be changed")
        if (
            quote.deposit_paid_at is not None
            or quote.deposit_checkout_session_id is not None
            or quote.deposit_payment_intent_id is not None
            or quote.converted_job_id is not None
            or quote.converted_invoice_id is not None
        ):
            raise ConflictError(
                "This quote has payment or conversion history and can no longer be changed"
            )
        return quote
