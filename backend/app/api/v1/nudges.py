"""Human nudge management endpoints."""

import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.elements import ColumnElement

from app.api.deps import (
    DB,
    CurrentMembership,
    CurrentUser,
    WorkspaceAccess,
    require_capability,
    require_route_capabilities,
)
from app.core.permissions import Capability, role_can
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.contact import Contact
from app.models.human_nudge import HumanNudge
from app.models.workspace import WorkspaceIntegration
from app.schemas.nudge import (
    NudgeActRequest,
    NudgeClearAllResponse,
    NudgeListResponse,
    NudgeResponse,
    NudgeSettingsResponse,
    NudgeSettingsUpdate,
    NudgeSnoozeRequest,
    NudgeStatsResponse,
)
from app.services.cards.card_service import CardService
from app.services.cards.card_templates import render_template

# Nudges are AI follow-up suggestions about specific customers: every response
# carries ``contact_name``, ``contact_phone`` and ``contact_company``. That is
# the same PII ``/contacts`` gates, so ``crm:read`` is the floor for the whole
# router — reads and the act/dismiss/snooze writes alike, since acting on a
# nudge requires seeing whose it is. Declared on the router so a new endpoint
# inherits the gate rather than defaulting open.
router = APIRouter(dependencies=[Depends(require_capability(Capability.CRM_READ))])


def _nudge_to_response(nudge: HumanNudge) -> NudgeResponse:
    """Convert a HumanNudge model to a NudgeResponse, populating contact fields."""
    contact = nudge.contact
    return NudgeResponse(
        id=nudge.id,
        workspace_id=nudge.workspace_id,
        contact_id=nudge.contact_id,
        nudge_type=nudge.nudge_type,
        title=nudge.title,
        message=nudge.message,
        suggested_action=nudge.suggested_action,
        priority=nudge.priority,
        due_date=nudge.due_date,
        source_date_field=nudge.source_date_field,
        status=nudge.status,
        snoozed_until=nudge.snoozed_until,
        delivered_via=nudge.delivered_via,
        delivered_at=nudge.delivered_at,
        acted_at=nudge.acted_at,
        assigned_to_user_id=nudge.assigned_to_user_id,
        created_at=nudge.created_at,
        contact_name=contact.full_name if contact else None,
        contact_phone=contact.phone_number if contact else None,
        contact_company=contact.company_name if contact else None,
    )


ACTIVE_NUDGE_STATUSES = ("pending", "sent", "snoozed")


def _nudge_visibility(workspace_id: uuid.UUID, user_id: int, role: str) -> ColumnElement[bool]:
    """Limit nudge access to the caller, plus CRM-managed legacy rows."""
    assignment = HumanNudge.assigned_to_user_id == user_id
    if role_can(role, Capability.CRM_WRITE):
        assignment = or_(assignment, HumanNudge.assigned_to_user_id.is_(None))
    return and_(HumanNudge.workspace_id == workspace_id, assignment)


async def _get_nudge_or_404(
    db: DB,
    nudge_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: int,
    role: str,
) -> HumanNudge:
    """Fetch a nudge only when it is visible to the caller."""
    result = await db.execute(
        select(HumanNudge)
        .options(joinedload(HumanNudge.contact))
        .where(
            HumanNudge.id == nudge_id,
            _nudge_visibility(workspace_id, user_id, role),
        )
    )
    nudge = result.unique().scalar_one_or_none()
    if not nudge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nudge not found",
        )
    return nudge


@router.get("", response_model=NudgeListResponse)
async def list_nudges(
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    status_filter: str | None = Query(None, alias="status"),
    nudge_type: str | None = Query(None),
    priority: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> NudgeListResponse:
    """List nudges visible to the caller with optional filters.

    Defaults to showing pending and sent nudges, ordered by due_date ascending.
    """
    query = (
        select(HumanNudge)
        .options(joinedload(HumanNudge.contact))
        .where(_nudge_visibility(workspace.id, current_user.id, membership.role))
        .order_by(HumanNudge.due_date.asc())
    )

    if status_filter:
        query = query.where(HumanNudge.status == status_filter)
    else:
        # Default: show pending and sent
        query = query.where(HumanNudge.status.in_(["pending", "sent"]))

    if nudge_type:
        query = query.where(HumanNudge.nudge_type == nudge_type)

    if priority:
        query = query.where(HumanNudge.priority == priority)

    result = await paginate(db, query, page=page, page_size=page_size, unique=True)

    return NudgeListResponse(
        items=[_nudge_to_response(n) for n in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/stats", response_model=NudgeStatsResponse)
async def get_nudge_stats(
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
) -> NudgeStatsResponse:
    """Get visible nudge counts grouped by status."""
    result = await db.execute(
        select(HumanNudge.status, func.count(HumanNudge.id))
        .where(_nudge_visibility(workspace.id, current_user.id, membership.role))
        .group_by(HumanNudge.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in result.all()}

    return NudgeStatsResponse(
        pending=counts.get("pending", 0),
        sent=counts.get("sent", 0),
        acted=counts.get("acted", 0),
        dismissed=counts.get("dismissed", 0),
        snoozed=counts.get("snoozed", 0),
        total=sum(counts.values()),
    )


@router.put("/clear-all", response_model=NudgeClearAllResponse)
async def clear_all_nudges(
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
) -> NudgeClearAllResponse:
    """Dismiss every active nudge currently visible to the caller."""
    result = await db.execute(
        update(HumanNudge)
        .where(
            _nudge_visibility(workspace.id, current_user.id, membership.role),
            HumanNudge.status.in_(ACTIVE_NUDGE_STATUSES),
        )
        .values(status="dismissed")
        .returning(HumanNudge.id)
    )
    dismissed_count = len(result.scalars().all())
    await db.commit()
    return NudgeClearAllResponse(dismissed_count=dismissed_count)


@router.put("/{nudge_id}/act", response_model=NudgeResponse)
async def act_on_nudge(
    nudge_id: uuid.UUID,
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    body: NudgeActRequest | None = None,
) -> NudgeResponse:
    """Mark a visible nudge as acted, optionally dispatching an action."""
    nudge = await _get_nudge_or_404(db, nudge_id, workspace.id, current_user.id, membership.role)

    if body and body.action_taken == "send_card":
        # Load contact for address
        contact_result = await db.execute(select(Contact).where(Contact.id == nudge.contact_id))
        contact = contact_result.scalar_one_or_none()
        if not contact or not contact.has_address:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Contact does not have a complete mailing address.",
            )

        # Load Lob integration
        integration_result = await db.execute(
            apply_workspace_scope(
                select(WorkspaceIntegration),
                WorkspaceIntegration,
                workspace.id,
            ).where(
                WorkspaceIntegration.integration_type == "lob",
                WorkspaceIntegration.is_active.is_(True),
            )
        )
        integration = integration_result.scalar_one_or_none()
        if not integration:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Card service not configured. Set up Lob in Settings > Integrations.",
            )

        # Get sender address from workspace card settings
        card_settings: dict[str, str] = workspace.settings.get("card_service", {})
        if not card_settings.get("from_name") or not card_settings.get("from_address_line1"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Sender address not configured in card settings.",
            )

        # Render template
        front_html, back_html = render_template(
            nudge.nudge_type, contact.first_name, card_settings["from_name"]
        )

        # Send postcard via Lob
        api_key: str = integration.credentials.get("api_key", "")
        card_svc = CardService(api_key=api_key)
        try:
            await card_svc.send_postcard(
                to_name=contact.full_name,
                to_address_line1=contact.address_line1 or "",
                to_address_city=contact.address_city or "",
                to_address_state=contact.address_state or "",
                to_address_zip=contact.address_zip or "",
                from_name=card_settings["from_name"],
                from_address_line1=card_settings["from_address_line1"],
                from_address_city=card_settings.get("from_address_city", ""),
                from_address_state=card_settings.get("from_address_state", ""),
                from_address_zip=card_settings.get("from_address_zip", ""),
                front_html=front_html,
                back_html=back_html,
                to_address_line2=contact.address_line2 or "",
                from_address_line2=card_settings.get("from_address_line2", ""),
            )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to send card: {exc.response.text}",
            ) from exc

    nudge.status = "acted"
    nudge.acted_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(nudge)

    return _nudge_to_response(nudge)


@router.put("/{nudge_id}/dismiss", response_model=NudgeResponse)
async def dismiss_nudge(
    nudge_id: uuid.UUID,
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
) -> NudgeResponse:
    """Dismiss a visible nudge."""
    nudge = await _get_nudge_or_404(db, nudge_id, workspace.id, current_user.id, membership.role)

    nudge.status = "dismissed"

    await db.commit()
    await db.refresh(nudge)

    return _nudge_to_response(nudge)


@router.put("/{nudge_id}/snooze", response_model=NudgeResponse)
async def snooze_nudge(
    nudge_id: uuid.UUID,
    body: NudgeSnoozeRequest,
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
) -> NudgeResponse:
    """Snooze a visible nudge until a specified time."""
    nudge = await _get_nudge_or_404(db, nudge_id, workspace.id, current_user.id, membership.role)

    nudge.status = "snoozed"
    nudge.snoozed_until = body.snooze_until

    await db.commit()
    await db.refresh(nudge)

    return _nudge_to_response(nudge)


# ── Nudge Settings (stored in workspace.settings JSONB) ──────────────


settings_router = APIRouter(
    dependencies=[
        Depends(
            require_route_capabilities(Capability.WORKSPACE_MANAGE, Capability.WORKSPACE_MANAGE)
        )
    ]
)


@settings_router.get("", response_model=NudgeSettingsResponse)
async def get_nudge_settings(
    workspace: WorkspaceAccess,
) -> NudgeSettingsResponse:
    """Get workspace nudge settings."""
    nudge_settings = workspace.settings.get("nudge_settings", {})
    return NudgeSettingsResponse(**nudge_settings)


@settings_router.put("", response_model=NudgeSettingsResponse)
async def update_nudge_settings(
    update: NudgeSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
) -> NudgeSettingsResponse:
    """Update workspace nudge settings."""
    current_settings = dict(workspace.settings)
    nudge_settings = current_settings.get("nudge_settings", {})

    update_data = update.model_dump(exclude_unset=True)
    nudge_settings.update(update_data)
    current_settings["nudge_settings"] = nudge_settings
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return NudgeSettingsResponse(**workspace.settings.get("nudge_settings", {}))
