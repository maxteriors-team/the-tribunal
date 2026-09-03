"""On-site upsell business logic.

The narrow surface a lead technician sells an add-on through while standing in
the customer's driveway. It exists because field roles deliberately have no
``crm:read`` and no ``billing:read`` (see :mod:`app.core.permissions`): rather
than widening those tiers — which would hand every technician the whole contact
book and the whole price book — this service re-derives a *much* smaller view
from the one thing a technician legitimately owns, the jobs they are assigned to.

Every public method takes the caller's ``user_id`` and ``role`` and enforces two
invariants:

1. **Job scoping.** A restricted caller (see
   :func:`app.core.permissions.upsell_job_scope_required`) may only touch a job
   that is tagged to their technician record or routed to one of their crews —
   the same visibility rule as their calendar, so the upsell surface can never
   show more than the schedule already does.
2. **Catalog scoping.** Only ``is_attachable`` + ``is_active`` catalog items are
   listed or accepted on a line item, so a technician sees the add-on menu rather
   than the workspace's full pricing.

A job the caller is not assigned to raises ``JobNotFoundError`` (404), never a
403: a 403 would confirm the job exists and turn this into an enumeration oracle
for a workspace's job ids.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Capability, role_can, upsell_job_scope_required
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, Technician
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.pricing import PricingSettings, UpsellRankConfig
from app.schemas.proposal_wizard import ProposalCarePlan
from app.schemas.quote import (
    QuoteCreate,
    QuoteDeliverResult,
    QuoteDetailResponse,
    QuoteLineItemCreate,
)
from app.schemas.upsell import (
    UpsellCarePlanResponse,
    UpsellCarePlanSelection,
    UpsellCatalogItem,
    UpsellCatalogResponse,
    UpsellCustomer,
    UpsellJob,
    UpsellJobListResponse,
    UpsellMyStats,
    UpsellQuoteRequest,
    UpsellRankProgress,
)
from app.services.field_service.exceptions import JobNotFoundError
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.quote_service import QuoteService
from app.services.upsell.exceptions import (
    UpsellCarePlanUnavailableError,
    UpsellItemNotAttachableError,
    UpsellNoLineItemsError,
    UpsellNotASellerError,
    UpsellProposalLimitError,
    UpsellQuoteNotForJobError,
)

logger = structlog.get_logger()


def _rank_progress(revenue: float, ranks: list[UpsellRankConfig]) -> UpsellRankProgress | None:
    """Place ``revenue`` on the workspace's selling ladder.

    Returns ``None`` when no ranks are configured — the default — so a workspace
    that has not defined a compensation ladder simply shows none, rather than
    this codebase inventing rank names and payouts on an operator's behalf.

    ``ranks`` arrives sorted ascending (enforced by ``UpsellConfig``). Progress is
    measured from the *current* rung's threshold rather than from zero, so a
    technician who just ranked up sees an almost-empty bar toward the next rung
    instead of an almost-full one.
    """
    if not ranks:
        return None

    current = None
    nxt = None
    for rank in ranks:
        if revenue >= rank.threshold:
            current = rank
        else:
            nxt = rank
            break

    if nxt is None:
        # Top of the ladder: no target left to chase.
        return UpsellRankProgress(
            current_key=current.key if current else None,
            current_name=current.name if current else None,
            current_reward=current.reward if current else None,
        )

    floor = current.threshold if current else 0.0
    span = nxt.threshold - floor
    return UpsellRankProgress(
        current_key=current.key if current else None,
        current_name=current.name if current else None,
        current_reward=current.reward if current else None,
        next_name=nxt.name,
        next_threshold=nxt.threshold,
        next_reward=nxt.reward,
        amount_to_next=round(nxt.threshold - revenue, 2),
        # A zero-width span (two ranks at the same threshold) would divide by
        # zero; treat the rung as already reached.
        progress=round(min(1.0, max(0.0, (revenue - floor) / span)), 4) if span > 0 else 1.0,
    )


# ``attributes`` flag -> human unit shown next to the price. The price book stores
# a rate in ``unit_price`` and marks *how* it is measured out of band, so without
# this translation a per-foot rate is indistinguishable from a job total on the
# technician's menu.
_PRICE_UNIT_FLAGS: tuple[tuple[str, str], ...] = (("per_linear_foot", "per linear foot"),)


def _price_unit(attributes: dict[str, Any] | None) -> str | None:
    """Return the display unit for an item's price, or None for a flat price."""
    if not attributes:
        return None
    for flag, label in _PRICE_UNIT_FLAGS:
        if attributes.get(flag):
            return label
    return None


class UpsellService:
    """Scoped read/write surface for selling add-ons from the field."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="upsell_service")

    # ------------------------------------------------------------------ #
    # Pricing
    # ------------------------------------------------------------------ #
    async def _pricing_config(self, workspace_id: uuid.UUID) -> PricingSettings:
        """The workspace's sales-pricing config (defaults when unset/invalid)."""
        workspace = await self.db.get(Workspace, workspace_id)
        if workspace is None:
            raise JobNotFoundError("Workspace not found")
        return get_pricing_config(workspace)

    @staticmethod
    def _sell_price(amount: float, config: PricingSettings) -> float:
        """Return the configured customer price through the shared legacy adapter.

        The same direct-price function serves the field menu and office wizard,
        so a fixture quoted in either place matches to the cent.
        """
        return float(pp.gross_up_price(amount, config))

    @staticmethod
    def _fulfillment_parts(
        payload: UpsellQuoteRequest,
        catalog: dict[uuid.UUID, CatalogItem],
    ) -> list[dict[str, Any]]:
        """Build the internal order list emailed when the customer approves.

        Configured component SKUs win. A catalog item without a component BOM
        falls back to its own SKU, then its name, so an accepted field order
        never disappears merely because the price book is not fully enriched.
        Custom lines are included by name and explicitly marked for sourcing
        review because the technician cannot attach a SKU to them.
        """
        parts: dict[str, dict[str, Any]] = {}

        def add_part(key: str, description: str | None, quantity: float) -> None:
            normalized = key.strip()
            if not normalized or quantity <= 0:
                return
            existing = parts.get(normalized)
            if existing is not None:
                existing["qty"] = float(existing["qty"]) + quantity
                return
            parts[normalized] = {
                "sku": normalized,
                "description": description,
                "qty": quantity,
            }

        for requested in payload.line_items:
            item = catalog[requested.catalog_item_id]
            component_added = False
            for component in item.components or []:
                if not isinstance(component, dict):
                    continue
                sku = str(component.get("sku") or "").strip()
                if not sku:
                    continue
                try:
                    component_quantity = float(component.get("qty", 1))
                except (TypeError, ValueError):
                    continue
                add_part(
                    sku,
                    str(component.get("description") or "").strip() or None,
                    component_quantity * requested.quantity,
                )
                component_added = True
            if not component_added:
                add_part(
                    item.sku or item.name,
                    item.description or item.name,
                    requested.quantity,
                )

        for custom in payload.custom_line_items:
            add_part(
                custom.name,
                "Custom line item — confirm sourcing requirements",
                custom.quantity,
            )

        return list(parts.values())

    # ------------------------------------------------------------------ #
    # Job scoping — the security boundary every other method sits behind
    # ------------------------------------------------------------------ #
    async def _visible_job(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        user_id: int,
        role: str,
    ) -> Job:
        """Load ``job_id`` if the caller is allowed to upsell on it.

        Mirrors ``JobService.list_for_user``: a job is the caller's when it is
        tagged directly to one of their technician records or routed to a crew
        they belong to. Unrestricted callers (``billing:write`` holders) skip the
        assignment predicate but stay workspace-scoped.

        Raises:
            JobNotFoundError: when the job is absent, in another workspace, or
                simply not the caller's — deliberately indistinguishable.
        """
        criteria: list[Any] = [Job.id == job_id, Job.workspace_id == workspace_id]

        if upsell_job_scope_required(role):
            tech_rows = (
                await self.db.execute(
                    select(Technician.id, Technician.crew_id).where(
                        Technician.workspace_id == workspace_id,
                        Technician.user_id == user_id,
                    )
                )
            ).all()
            # A login with no technician record is not a field worker, so it owns
            # no jobs at all. Bail before building an ``IN ()`` over an empty list.
            if not tech_rows:
                raise JobNotFoundError()

            technician_ids = [row[0] for row in tech_rows]
            crew_ids = [row[1] for row in tech_rows if row[1] is not None]

            visibility = [
                Job.id.in_(
                    select(JobAssignment.job_id).where(
                        JobAssignment.technician_id.in_(technician_ids)
                    )
                )
            ]
            if crew_ids:
                visibility.append(Job.crew_id.in_(crew_ids))
            criteria.append(or_(*visibility))

        job = (await self.db.execute(select(Job).where(*criteria))).scalar_one_or_none()
        if job is None:
            raise JobNotFoundError()
        return job

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def list_jobs(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
        role: str,
    ) -> UpsellJobListResponse:
        """The caller's upsellable jobs, newest scheduled first.

        Returns an empty list rather than an error when the login has no
        technician record: not being a field worker is a normal state, not a
        failure.
        """
        criteria: list[Any] = [Job.workspace_id == workspace_id]

        if upsell_job_scope_required(role):
            tech_rows = (
                await self.db.execute(
                    select(Technician.id, Technician.crew_id).where(
                        Technician.workspace_id == workspace_id,
                        Technician.user_id == user_id,
                    )
                )
            ).all()
            if not tech_rows:
                return UpsellJobListResponse(items=[], total=0)

            technician_ids = [row[0] for row in tech_rows]
            crew_ids = [row[1] for row in tech_rows if row[1] is not None]
            visibility = [
                Job.id.in_(
                    select(JobAssignment.job_id).where(
                        JobAssignment.technician_id.in_(technician_ids)
                    )
                )
            ]
            if crew_ids:
                visibility.append(Job.crew_id.in_(crew_ids))
            criteria.append(or_(*visibility))

        query = (
            select(Job)
            .where(*criteria)
            .order_by(Job.scheduled_start.is_(None), Job.scheduled_start.desc())
        )
        rows = (await self.db.execute(query)).scalars().all()
        items = [
            UpsellJob(
                id=job.id,
                title=job.title,
                status=str(job.status),
                scheduled_start=job.scheduled_start,
                contact_id=job.contact_id,
            )
            for job in rows
        ]
        return UpsellJobListResponse(items=items, total=len(items))

    async def job_customer(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        user_id: int,
        role: str,
    ) -> UpsellCustomer:
        """The customer on a job the caller is assigned to.

        A deliberately thin projection — name, phone, email, service address. The
        technician needs enough to greet the customer and put an address on a
        proposal, not the contact's pipeline, notes, tags, or message history.
        """
        job = await self._visible_job(workspace_id, job_id, user_id, role)

        contact = (
            await self.db.execute(
                select(Contact).where(
                    Contact.id == job.contact_id,
                    Contact.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if contact is None:
            # The job's customer was deleted out from under it. Nothing to sell to.
            raise JobNotFoundError("Customer not found for this job")

        return UpsellCustomer(
            contact_id=contact.id,
            full_name=contact.full_name,
            phone_number=contact.phone_number,
            email=contact.email,
            address_line1=contact.address_line1,
            address_city=contact.address_city,
            address_state=contact.address_state,
            address_zip=contact.address_zip,
        )

    async def list_attachable_catalog(
        self,
        workspace_id: uuid.UUID,
        *,
        attach_target: str | None = None,
        role: str | None = None,
    ) -> UpsellCatalogResponse:
        """The add-on menu: active, attachable catalog items only.

        ``attach_target`` narrows to items that ride along with a given service
        category (e.g. ``landscape`` lighting attached to a wash). Matching is
        case-insensitive because ``attach_targets`` is operator-typed free text,
        and an item with an empty ``attach_targets`` is treated as unrestricted —
        the column's documented meaning is "no restriction recorded".

        Prices are the configured client selling amounts — see :meth:`_sell_price`.

        ``role`` resolves ``proposal_limit`` on the response so the UI can warn a
        capped technician before they build. Omitting it reports no limit, which
        is display-only — the cap is enforced on write in
        :meth:`_enforce_proposal_limit` regardless of what this read says.
        """
        config = await self._pricing_config(workspace_id)
        query = select(CatalogItem).where(
            CatalogItem.workspace_id == workspace_id,
            CatalogItem.is_active.is_(True),
            CatalogItem.is_attachable.is_(True),
        )
        rows = (await self.db.execute(query.order_by(CatalogItem.name.asc()))).scalars().all()

        if attach_target:
            wanted = attach_target.strip().casefold()
            rows = [
                item
                for item in rows
                if not item.attach_targets
                or any(
                    (target or "").strip().casefold() == wanted for target in item.attach_targets
                )
            ]

        items = [
            UpsellCatalogItem(
                id=item.id,
                name=item.name,
                description=item.description,
                unit_price=self._sell_price(float(item.unit_price), config),
                taxable=item.taxable,
                service_category=item.service_category,
                attach_targets=list(item.attach_targets or []),
                price_unit=_price_unit(item.attributes),
            )
            for item in rows
        ]
        limit = config.upsell.field_proposal_limit
        if role is None or role_can(role, Capability.UPSELL_SELL_UNCAPPED):
            limit = None
        return UpsellCatalogResponse(items=items, total=len(items), proposal_limit=limit)

    async def list_care_plans(
        self,
        workspace_id: uuid.UUID,
        *,
        fixture_count: int,
    ) -> UpsellCarePlanResponse:
        """Price every Care Plan tier for a counted number of fixtures.

        Priced through :func:`app.services.quotes.proposal_pricing.price_care_plan`
        — the same function the sales wizard and the public proposal page use — so
        a technician quoting Gold in a driveway and an office rep quoting Gold in
        the wizard cannot arrive at different numbers.

        A workspace with no configured tiers returns ``configured=False`` with an
        empty list rather than an error: not selling maintenance is a normal
        state, and the UI renders it as guidance.
        """
        workspace = await self.db.get(Workspace, workspace_id)
        if workspace is None:
            raise JobNotFoundError("Workspace not found")

        config = get_pricing_config(workspace)
        if not config.care_plan.tiers:
            return UpsellCarePlanResponse(
                fixture_count=fixture_count,
                free_fixtures=config.care_plan.free_fixtures,
                options=[],
                configured=False,
            )

        return UpsellCarePlanResponse(
            fixture_count=fixture_count,
            free_fixtures=config.care_plan.free_fixtures,
            options=pp.price_care_plan(fixture_count, config),
            configured=True,
        )

    async def my_selling_stats(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
        *,
        today: date | None = None,
    ) -> UpsellMyStats:
        """This technician's own selling numbers for the current calendar month.

        Scoped to ``created_by_id == user_id`` and nothing else. A technician sees
        their own performance and no colleague's: the workspace-wide breakdown
        already exists behind ``reports:view`` for owners
        (``sales_performance_service.by_closer``), and surfacing peers' revenue to
        the narrowest tier in the product would be a data leak wearing a
        leaderboard costume.

        Cohorted on **creation**, matching the sales-performance report, so a
        proposal and the decision it earns stay in the same month and the close
        rate answers "of what I sent in June, how much closed?".

        Drafts are excluded throughout: a draft never reached a customer, so it is
        not a sales attempt. ``close_rate`` is ``None`` rather than ``0`` when
        nothing was sent, so a quiet month never renders as a 0% close rate.
        """
        reference = today or datetime.now(UTC).date()
        period_start = reference.replace(day=1)
        period_end = (period_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        rows = (
            (
                await self.db.execute(
                    select(
                        Quote.status,
                        Quote.total,
                        Quote.proposal_document,
                    ).where(
                        Quote.workspace_id == workspace_id,
                        Quote.created_by_id == user_id,
                        Quote.status != "draft",
                        Quote.created_at >= datetime.combine(period_start, time.min, tzinfo=UTC),
                        Quote.created_at
                        < datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=UTC),
                    )
                )
            )
            .tuples()
            .all()
        )

        sent = len(rows)
        approved = [row for row in rows if row[0] == "approved"]
        revenue = round(sum(float(row[1]) for row in approved), 2)
        care_plans = sum(1 for row in approved if (row[2] or {}).get("care_plan"))

        config = await self._pricing_config(workspace_id)
        return UpsellMyStats(
            period_start=period_start,
            period_end=period_end,
            proposals_sent=sent,
            proposals_approved=len(approved),
            revenue_approved=revenue,
            care_plans_sold=care_plans,
            close_rate=round(len(approved) / sent, 4) if sent else None,
            rank=_rank_progress(revenue, config.upsell.ranks),
        )

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #
    async def create_quote(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        payload: UpsellQuoteRequest,
        *,
        user_id: int,
        role: str,
    ) -> QuoteDetailResponse:
        """Build a draft add-on proposal for the customer on ``job_id``.

        Catalog lines are always priced from the server-side price book. Custom
        lines are the deliberate exception: the lead supplies their name and
        customer price, but cannot submit zero/negative values, more than ten
        lines, or a combined total above the workspace's on-site proposal limit.

        The quote is attributed to the caller (``created_by_id``) so attach-rate
        and attach-value reporting can pay the right person a spiff.

        A Care Plan rides in ``proposal_document`` rather than as a line item —
        see :meth:`_care_plan_document` for why that distinction is the whole
        feature and not a storage detail.

        Raises:
            UpsellNoLineItemsError: nothing sold at all — no add-ons and no plan.
                [400]
            UpsellItemNotAttachableError: an item that is missing, archived, in
                another workspace, or simply not flagged ``is_attachable``. [400]
            UpsellCarePlanUnavailableError: an unknown or no-longer-offered tier.
                [400]
            UpsellNotASellerError: the caller's role may not sell. [403]
            UpsellProposalLimitError: over the crew lead's on-site limit. [400]
        """
        self._require_seller(role)
        job = await self._visible_job(workspace_id, job_id, user_id, role)

        # A Care Plan on its own is a complete sale: signing an existing system
        # onto maintenance adds no hardware, so "empty" means neither.
        if not payload.line_items and not payload.custom_line_items and payload.care_plan is None:
            raise UpsellNoLineItemsError()

        requested_ids = [line.catalog_item_id for line in payload.line_items]
        # One query for the whole basket, filtered on the attachable predicate, so
        # an id that is real but not sellable here is indistinguishable from one
        # that does not exist.
        sellable = {
            item.id: item
            for item in (
                await self.db.execute(
                    select(CatalogItem).where(
                        CatalogItem.workspace_id == workspace_id,
                        CatalogItem.is_active.is_(True),
                        CatalogItem.is_attachable.is_(True),
                        CatalogItem.id.in_(requested_ids),
                    )
                )
            )
            .scalars()
            .all()
        }

        missing = [str(item_id) for item_id in requested_ids if item_id not in sellable]
        if missing:
            raise UpsellItemNotAttachableError(
                "These items are not available as add-ons: " + ", ".join(sorted(set(missing)))
            )

        # Grossed up here too, not just on the menu: the number the technician
        # read aloud must be the number on the proposal the customer approves.
        config = await self._pricing_config(workspace_id)
        line_items = [
            QuoteLineItemCreate(
                name=sellable[line.catalog_item_id].name,
                description=sellable[line.catalog_item_id].description,
                quantity=line.quantity,
                unit_price=self._sell_price(
                    float(sellable[line.catalog_item_id].unit_price), config
                ),
                catalog_item_id=line.catalog_item_id,
            )
            for line in payload.line_items
        ]
        line_items.extend(
            QuoteLineItemCreate(
                name=line.name,
                quantity=line.quantity,
                unit_price=line.unit_price,
            )
            for line in payload.custom_line_items
        )

        # Enforced BEFORE the quote is written, for the same reason as the tier
        # check below: ``create_quote`` commits on its own, so refusing after it
        # would leave an orphaned draft the technician cannot see or delete.
        self._enforce_proposal_limit(line_items, config, role)

        # Priced and validated BEFORE the quote is written: a bad tier key must
        # fail without leaving a stray draft behind, because ``create_quote``
        # commits on its own.
        care_plan_document = (
            await self._care_plan_document(workspace_id, payload.care_plan)
            if payload.care_plan is not None
            else None
        )
        fulfillment = self._fulfillment_parts(payload, sellable)
        proposal_document: dict[str, Any] = {}
        if care_plan_document is not None:
            proposal_document["care_plan"] = care_plan_document
        if fulfillment:
            proposal_document["fulfillment"] = fulfillment

        one_time_total = sum(item.unit_price * item.quantity for item in line_items)
        quote_in = QuoteCreate(
            contact_id=job.contact_id,
            service_location_id=job.service_location_id,
            title=payload.title or self._default_title(job, payload, care_plan_document),
            line_items=line_items,
            deposit_percentage=100 if one_time_total > 0 else None,
            notes=payload.notes,
        )

        created = await QuoteService(self.db).create_quote(
            workspace_id,
            quote_in,
            created_by_id=user_id,
            is_onsite_upsell=True,
        )

        if proposal_document:
            quote = await self.db.get(Quote, created.id)
            if quote is not None:
                # Fulfillment is internal-only (the public serializer strips it),
                # while Care Plan data provisions the recurring service on approval.
                document = dict(quote.proposal_document or {})
                document.update(proposal_document)
                quote.proposal_document = document
                await self.db.flush()
                created.proposal_document = document

        self.log.info(
            "upsell_quote_created",
            workspace_id=str(workspace_id),
            job_id=str(job_id),
            quote_id=str(created.id),
            user_id=user_id,
            line_count=len(line_items),
            care_plan_tier=(care_plan_document or {}).get("selected"),
        )
        return created

    @staticmethod
    def _require_seller(role: str) -> None:
        """Refuse a role that may not sell on site.

        A plain ``technician`` does not quote — they hand the opportunity to their
        crew lead. The router already gates this with ``CanUpsell``; repeating it
        here means the rule survives a second caller that forgets the dependency,
        and it is checked before any write so no orphaned draft is left behind.

        Raises:
            UpsellNotASellerError: the role lacks ``upsell:sell``. [403]
        """
        if not role_can(role, Capability.UPSELL_SELL):
            raise UpsellNotASellerError()

    @staticmethod
    def _enforce_proposal_limit(
        line_items: list[QuoteLineItemCreate],
        config: PricingSettings,
        role: str,
    ) -> None:
        """Hold a crew lead to the workspace's on-site proposal limit.

        The crew lead is the only on-site seller: a plain ``technician`` cannot
        reach this code at all, lacking ``upsell:sell``. Office tiers hold
        ``upsell:sell_uncapped`` and are waved through, so this is the ceiling
        on what gets committed from a driveway without office review.

        Server-side by necessity, not convenience. The technician's device cannot
        be trusted with this — it is the same phone that cannot be trusted with a
        ``unit_price`` — so the client's warning is a courtesy and this is the
        control.

        Measured on the direct one-time total the customer is charged, and
        deliberately not on the recurring care plan: see
        :class:`~app.schemas.pricing.UpsellConfig`.

        No limit configured (the default) means no cap, so a workspace that never
        asked for one is unaffected.

        Raises:
            UpsellProposalLimitError: over the limit. [400]
        """
        limit = config.upsell.field_proposal_limit
        if limit is None or role_can(role, Capability.UPSELL_SELL_UNCAPPED):
            return

        total = sum(item.unit_price * item.quantity for item in line_items)
        if total > limit:
            raise UpsellProposalLimitError(total, limit)

    @staticmethod
    def _default_title(
        job: Job,
        payload: UpsellQuoteRequest,
        care_plan_document: dict[str, Any] | None,
    ) -> str:
        """Name the proposal after what it actually sells.

        A care-plan-only proposal titled "Add-on for Roof soft wash" reads as a
        mistake to the customer approving it.
        """
        if (
            care_plan_document is not None
            and not payload.line_items
            and not payload.custom_line_items
        ):
            return f"Care plan for {job.title}"[:200]
        return f"Add-on for {job.title}"[:200]

    async def _care_plan_document(
        self,
        workspace_id: uuid.UUID,
        selection: UpsellCarePlanSelection,
    ) -> dict[str, Any]:
        """Build the frozen ``care_plan`` snapshot for a technician's selection.

        **A Care Plan is a subscription, not a line item, and that is the whole
        point of this method.** On approval,
        :class:`~app.services.recurring_jobs.service_plan_provisioner.ServicePlanProvisioner`
        reads ``proposal_document.care_plan.selected`` and creates the recurring
        template that puts maintenance visits on the dispatch board. Selling the
        plan as a catalog line item instead would take the customer's money once,
        provision nothing, and schedule no visits — the client would be "on Gold"
        in nobody's records. Writing the snapshot is what makes the sale real.

        The full priced ``options`` list is written, not just the chosen key,
        because the provisioner reads the selected option's ``visits`` to derive
        the plan's recurrence and its ``name`` for the plan title — and because
        freezing the snapshot means a later pricing-config edit cannot
        retroactively change what this customer bought. This is the same shape
        :func:`app.services.quotes.proposal_builder.build_proposal_document`
        writes, so the public proposal page renders it with no special-casing.
        """
        priced = await self.list_care_plans(workspace_id, fixture_count=selection.fixture_count)
        if not priced.configured:
            raise UpsellCarePlanUnavailableError("This workspace does not offer care plans yet")

        chosen = next(
            (option for option in priced.options if option.key == selection.tier_key),
            None,
        )
        if chosen is None:
            raise UpsellCarePlanUnavailableError()

        return ProposalCarePlan(
            fixture_count=priced.fixture_count,
            free_fixtures=priced.free_fixtures,
            options=priced.options,
            selected=chosen.key,
        ).model_dump(mode="json")

    async def _quote_for_job(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        user_id: int,
        role: str,
    ) -> Quote:
        """Load a quote only when both it and its customer belong to this job."""
        self._require_seller(role)
        job = await self._visible_job(workspace_id, job_id, user_id, role)
        quote = (
            await self.db.execute(
                select(Quote).where(
                    Quote.id == quote_id,
                    Quote.workspace_id == workspace_id,
                    Quote.contact_id == job.contact_id,
                )
            )
        ).scalar_one_or_none()
        if quote is None:
            raise UpsellQuoteNotForJobError()
        return quote

    async def present_quote(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        user_id: int,
        role: str,
    ) -> QuoteDetailResponse:
        """Publish a job-scoped proposal for approval on the technician's device."""
        await self._quote_for_job(workspace_id, job_id, quote_id, user_id=user_id, role=role)
        self.log.info(
            "upsell_quote_presented",
            workspace_id=str(workspace_id),
            job_id=str(job_id),
            quote_id=str(quote_id),
            user_id=user_id,
        )
        return await QuoteService(self.db).prepare_for_in_person_approval(workspace_id, quote_id)

    async def deliver_quote(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        channel: str,
        user_id: int,
        role: str,
    ) -> QuoteDeliverResult:
        """Send a proposal to the customer on a job the caller is assigned to.

        The quote must belong to the assigned job's customer. No destination
        override is accepted; delivery falls back to the contact's own phone or
        email.
        """
        await self._quote_for_job(workspace_id, job_id, quote_id, user_id=user_id, role=role)
        self.log.info(
            "upsell_quote_delivered",
            workspace_id=str(workspace_id),
            job_id=str(job_id),
            quote_id=str(quote_id),
            user_id=user_id,
            channel=channel,
        )
        return await QuoteService(self.db).deliver_quote(workspace_id, quote_id, channel=channel)
