"""Referral-partner endpoints: roster CRUD plus the production scoreboard.

Mounted under a workspace. Reads are available to any workspace member; writes
are gated to managers and up (:data:`app.api.deps.WorkspaceManager`), because the
partner roster is relationship data an owner curates — the same posture crews and
technicians get in :mod:`app.api.v1.field_service`.

Writes run on the transactional session so a failed name-uniqueness or
cross-tenant contact check rolls back cleanly, and ``ServiceErrorRoute`` maps the
service layer's typed errors onto HTTP responses at the boundary.
"""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import DB, TransactionalDB, WorkspaceAccess, WorkspaceManager
from app.api.service_errors import ServiceErrorRoute
from app.models.referral_partner import ReferralPartnerType
from app.schemas.referral_partner import (
    DEFAULT_QUIET_AFTER_DAYS,
    ReferralPartnerCreate,
    ReferralPartnerListResponse,
    ReferralPartnerResponse,
    ReferralPartnerScoreboardResponse,
    ReferralPartnerUpdate,
)
from app.services.lead_sources.referral_partner_service import ReferralPartnerService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=ReferralPartnerListResponse)
async def list_referral_partners(
    workspace: WorkspaceAccess,
    db: DB,
    is_active: bool | None = None,
    partner_type: ReferralPartnerType | None = None,
) -> ReferralPartnerListResponse:
    """List referral partners, optionally filtered by active state or type."""
    service = ReferralPartnerService(db)
    return await service.list(workspace.id, is_active=is_active, partner_type=partner_type)


@router.post("", response_model=ReferralPartnerResponse, status_code=201)
async def create_referral_partner(
    payload: ReferralPartnerCreate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> ReferralPartnerResponse:
    """Add a referral partner to the roster."""
    service = ReferralPartnerService(db)
    return await service.create(membership.workspace_id, payload.model_dump())


# Registered before `/{partner_id}` so FastAPI matches the static "scoreboard"
# path instead of trying to parse it as a UUID.
@router.get("/scoreboard", response_model=ReferralPartnerScoreboardResponse)
async def get_referral_partner_scoreboard(
    workspace: WorkspaceAccess,
    db: DB,
    quiet_after_days: int = Query(
        DEFAULT_QUIET_AFTER_DAYS,
        ge=1,
        le=3650,
        description="A partner is 'gone quiet' after this many days with no referral.",
    ),
    gone_quiet_only: bool = Query(
        False,
        description=(
            "Return only partners with at least one historical referral and "
            "nothing inside the window — the call list."
        ),
    ),
    is_active: bool | None = None,
    partner_type: ReferralPartnerType | None = None,
) -> ReferralPartnerScoreboardResponse:
    """Per-partner referrals, close rate, and revenue, ranked by revenue."""
    service = ReferralPartnerService(db)
    return await service.scoreboard(
        workspace.id,
        quiet_after_days=quiet_after_days,
        gone_quiet_only=gone_quiet_only,
        is_active=is_active,
        partner_type=partner_type,
    )


@router.get("/{partner_id}", response_model=ReferralPartnerResponse)
async def get_referral_partner(
    partner_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> ReferralPartnerResponse:
    """Get a single referral partner."""
    service = ReferralPartnerService(db)
    return await service.get(partner_id, workspace.id)


@router.put("/{partner_id}", response_model=ReferralPartnerResponse)
async def update_referral_partner(
    partner_id: uuid.UUID,
    payload: ReferralPartnerUpdate,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> ReferralPartnerResponse:
    """Update a referral partner."""
    service = ReferralPartnerService(db)
    return await service.update(
        partner_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/{partner_id}", status_code=204)
async def delete_referral_partner(
    partner_id: uuid.UUID,
    membership: WorkspaceManager,
    db: TransactionalDB,
) -> None:
    """Delete a referral partner. Their referred leads and jobs keep their history."""
    service = ReferralPartnerService(db)
    await service.delete(partner_id, membership.workspace_id)
