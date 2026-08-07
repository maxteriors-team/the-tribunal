"""On-site upsell business logic.

The narrow surface a field technician sells an add-on through while standing in
the customer's driveway. It exists because the ``field`` tier deliberately has no
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
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import upsell_job_scope_required
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Job, JobAssignment, Technician
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.pricing import PricingSettings
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
    UpsellQuoteRequest,
)
from app.services.field_service.exceptions import JobNotFoundError
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.pricing_config import get_pricing_config
from app.services.quotes.quote_service import QuoteService
from app.services.upsell.exceptions import (
    UpsellCarePlanUnavailableError,
    UpsellItemNotAttachableError,
    UpsellNoLineItemsError,
    UpsellQuoteNotForJobError,
)

logger = structlog.get_logger()

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
    def _sell_price(net: float, config: PricingSettings) -> float:
        """Convert a price-book figure into the price a client is actually charged.

        ``catalog_items.unit_price`` holds a **net** price. Every client-facing
        sales surface grosses it up by the back-end buffer (the Wisetack dealer
        fee, plus commission when ``commission.in_price`` is on) before showing a
        number: the wizard does it per fixture and per ad-hoc charge —
        ``proposal_builder`` calls it out as "rep enters net, we gross up (matches
        every other price)" — and the bistro and roofline estimators do the same.

        Skipping it would make this the one surface that sells at cost. On the
        real seeded price book that is an 11% margin leak at the default buffer
        (a $785 net uplight must sell for $882) and more wherever commission is
        baked into price. It matters more here than anywhere else precisely
        because of how this screen is designed: the technician cannot see the
        price book and cannot override a price, so a net figure handed to them is
        sold at net every time, with no human left to notice.

        Same function the wizard uses, so a fixture quoted in a driveway and the
        same fixture quoted from the office come out to the cent.
        """
        return float(pp.gross_up_price(net, config))

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
    ) -> UpsellCatalogResponse:
        """The add-on menu: active, attachable catalog items only.

        ``attach_target`` narrows to items that ride along with a given service
        category (e.g. ``landscape`` lighting attached to a wash). Matching is
        case-insensitive because ``attach_targets`` is operator-typed free text,
        and an item with an empty ``attach_targets`` is treated as unrestricted —
        the column's documented meaning is "no restriction recorded".

        Prices are **grossed up** to what a client is charged — see
        :meth:`_sell_price`.
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
        return UpsellCatalogResponse(items=items, total=len(items))

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

        The technician never sends a price: they send catalog item ids and
        quantities, and the server resolves the name and ``unit_price`` from the
        price book. That is the whole point of the restriction — a client that
        could post its own ``unit_price`` could discount the workspace's work to
        zero from a phone in a driveway.

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
        """
        job = await self._visible_job(workspace_id, job_id, user_id, role)

        # A Care Plan on its own is a complete sale: signing an existing system
        # onto maintenance adds no hardware, so "empty" means neither.
        if not payload.line_items and payload.care_plan is None:
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

        # Priced and validated BEFORE the quote is written: a bad tier key must
        # fail without leaving a stray draft behind, because ``create_quote``
        # commits on its own.
        care_plan_document = (
            await self._care_plan_document(workspace_id, payload.care_plan)
            if payload.care_plan is not None
            else None
        )

        quote_in = QuoteCreate(
            contact_id=job.contact_id,
            service_location_id=job.service_location_id,
            title=payload.title or self._default_title(job, payload, care_plan_document),
            line_items=line_items,
            notes=payload.notes,
        )

        created = await QuoteService(self.db).create_quote(
            workspace_id, quote_in, created_by_id=user_id
        )

        if care_plan_document is not None:
            quote = await self.db.get(Quote, created.id)
            if quote is not None:
                # Merge rather than assign: an upsell quote has no other snapshot
                # today, but clobbering a document is how a future caller silently
                # loses a customer's tier selection.
                document = dict(quote.proposal_document or {})
                document["care_plan"] = care_plan_document
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
    def _default_title(
        job: Job,
        payload: UpsellQuoteRequest,
        care_plan_document: dict[str, Any] | None,
    ) -> str:
        """Name the proposal after what it actually sells.

        A care-plan-only proposal titled "Add-on for Roof soft wash" reads as a
        mistake to the customer approving it.
        """
        if care_plan_document is not None and not payload.line_items:
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

        Two independent checks, and both are load-bearing:

        1. The **job** must be the caller's (:meth:`_visible_job`).
        2. The **quote** must be for that job's customer.

        Skipping the second would leave a hole big enough to matter: a technician
        legitimately assigned to one job could pass their own ``job_id`` with any
        other quote id in the workspace and blast that proposal out. Binding the
        quote to the job's ``contact_id`` means the only thing they can send is a
        proposal belonging to the customer whose driveway they are standing in.

        No destination override is accepted; :meth:`QuoteService.deliver_quote`
        falls back to the contact's own phone/email.

        Raises:
            JobNotFoundError: the job is not the caller's. [404]
            UpsellQuoteNotForJobError: the quote is missing, in another
                workspace, or belongs to a different customer. [404]
        """
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

        self.log.info(
            "upsell_quote_delivered",
            workspace_id=str(workspace_id),
            job_id=str(job_id),
            quote_id=str(quote_id),
            user_id=user_id,
            channel=channel,
        )
        return await QuoteService(self.db).deliver_quote(workspace_id, quote_id, channel=channel)
