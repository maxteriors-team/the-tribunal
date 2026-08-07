"""On-site upsell endpoints: sell an add-on from the customer's driveway.

Every route is gated on ``upsell:sell``, which the ``field`` tier holds. That
capability is *not* an access grant on its own — it only opens this router, and
this router hands each call to :class:`app.services.upsell.UpsellService`, which
re-scopes it to the jobs the caller is actually assigned to and to catalog items
flagged ``is_attachable``.

Hence the shape of these routes: they are keyed on ``job_id``, never on
``contact_id`` or a free catalog query. A technician reaches a customer *through*
a job they are on, which is the only relationship that justifies them seeing that
customer at all. Higher tiers (``billing:write`` holders) are not job-scoped
here, since they can already do all of this through the full quotes API.

Delivery is exposed here rather than via ``comms:send`` on the field tier: this
endpoint can only send *this* proposal to the destination already on the contact,
whereas ``comms:send`` would let a technician text anyone in the workspace.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DB, CanUpsell, CurrentUser, TransactionalDB
from app.api.service_errors import ServiceErrorRoute
from app.schemas.quote import QuoteDeliverResult, QuoteDetailResponse
from app.schemas.upsell import (
    UpsellCarePlanResponse,
    UpsellCatalogResponse,
    UpsellCustomer,
    UpsellDeliverRequest,
    UpsellJobListResponse,
    UpsellQuoteRequest,
)
from app.services.upsell import UpsellService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("/jobs", response_model=UpsellJobListResponse)
async def list_upsell_jobs(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanUpsell,
) -> UpsellJobListResponse:
    """Jobs the caller can sell an add-on on.

    Empty (not an error) when the login has no technician record — a login simply
    isn't a field worker yet.
    """
    service = UpsellService(db)
    return await service.list_jobs(workspace_id, current_user.id, membership.role)


@router.get("/jobs/{job_id}/customer", response_model=UpsellCustomer)
async def get_upsell_customer(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanUpsell,
) -> UpsellCustomer:
    """The customer on a job the caller is assigned to (404 when it isn't theirs)."""
    service = UpsellService(db)
    return await service.job_customer(workspace_id, job_id, current_user.id, membership.role)


@router.get("/catalog", response_model=UpsellCatalogResponse)
async def list_upsell_catalog(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanUpsell,
    attach_target: Annotated[
        str | None,
        Query(description="Only add-ons that attach to this service category"),
    ] = None,
) -> UpsellCatalogResponse:
    """The add-on menu: active, attachable price-book items only."""
    service = UpsellService(db)
    return await service.list_attachable_catalog(workspace_id, attach_target=attach_target)


@router.get("/care-plans", response_model=UpsellCarePlanResponse)
async def list_upsell_care_plans(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanUpsell,
    fixture_count: Annotated[
        int,
        Query(ge=0, le=1000, description="Fixtures the technician counted on site"),
    ] = 0,
) -> UpsellCarePlanResponse:
    """Price the workspace's Care Plan tiers for a counted fixture count.

    Priced by the same engine as the sales wizard, so a plan quoted in a driveway
    matches the one quoted from the office. Returns ``configured=false`` when the
    workspace sells no maintenance plans.
    """
    service = UpsellService(db)
    return await service.list_care_plans(workspace_id, fixture_count=fixture_count)


@router.post("/jobs/{job_id}/quote", response_model=QuoteDetailResponse, status_code=201)
async def create_upsell_quote(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: UpsellQuoteRequest,
    current_user: CurrentUser,
    db: TransactionalDB,
    membership: CanUpsell,
) -> QuoteDetailResponse:
    """Build a draft add-on proposal for the customer on this job.

    Prices come from the price book, never from the request body, and the quote is
    attributed to the caller so attach-rate reporting can credit the sale.

    May carry hardware add-ons, a Care Plan, or both. A Care Plan is written to
    ``proposal_document`` (not as a line item) so approving the proposal actually
    provisions the recurring maintenance visits.
    """
    service = UpsellService(db)
    return await service.create_quote(
        workspace_id,
        job_id,
        payload,
        user_id=current_user.id,
        role=membership.role,
    )


@router.post("/jobs/{job_id}/quote/{quote_id}/deliver", response_model=QuoteDeliverResult)
async def deliver_upsell_quote(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    quote_id: uuid.UUID,
    payload: UpsellDeliverRequest,
    current_user: CurrentUser,
    db: TransactionalDB,
    membership: CanUpsell,
) -> QuoteDeliverResult:
    """Text or email the add-on proposal to the customer on this job.

    The service verifies both that the job is the caller's *and* that the quote
    belongs to that job's customer, so a valid job id cannot be paired with an
    unrelated quote to send someone else's proposal. No ``to`` override is
    accepted — delivery goes to the contact's own phone/email.
    """
    service = UpsellService(db)
    return await service.deliver_quote(
        workspace_id,
        job_id,
        quote_id,
        channel=payload.channel,
        user_id=current_user.id,
        role=membership.role,
    )
