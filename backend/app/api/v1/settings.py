"""Settings endpoints for user profile, notifications, and workspace integrations."""

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    DB,
    CanManageComms,
    CanManageMembers,
    CanManageWorkspace,
    CanReadBilling,
    CanReadCRM,
    CanWriteBilling,
    CanWriteCRM,
    CanWriteOutreach,
    CanWritePipeline,
    CurrentUser,
    WorkspaceAccess,
)
from app.models.bookable_staff import BookableStaff
from app.models.google_calendar_connection import GoogleCalendarConnection
from app.models.inventory import InventoryItem
from app.models.message_template import MessageTemplate
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceIntegration, WorkspaceMembership
from app.schemas.attach_rules import (
    AttachRulesSettings,
    AttachRulesSettingsUpdate,
)
from app.schemas.deal_lifecycle import DealLifecycleSettings
from app.schemas.lead_source import LeadSourceCaptureSettings
from app.schemas.neighbor_outreach import (
    NeighborOutreachSettings,
    NeighborOutreachSettingsUpdate,
)
from app.schemas.opportunity import AutoPipelineSettings
from app.schemas.pricing import (
    BistroConfig,
    PricingSettings,
    PricingSettingsUpdate,
)
from app.schemas.proposal import (
    ProposalTemplateSettings,
    ProposalTemplateUpdate,
)
from app.schemas.quote_followup import (
    QuoteFollowupSettings,
    QuoteFollowupSettingsUpdate,
)
from app.schemas.quote_revival import (
    QuoteRevivalSettings,
    QuoteRevivalSettingsUpdate,
)
from app.schemas.speed_to_lead import (
    MissedCallTextbackSettingsResponse,
    MissedCallTextbackSettingsUpdate,
    SpeedToLeadMetrics,
    SpeedToLeadSettingsResponse,
    SpeedToLeadSettingsUpdate,
)
from app.schemas.user import (
    BusinessHoursSettings,
    BusinessHoursUpdate,
    CallForwardingSettings,
    CallForwardingUpdate,
    IntegrationsResponse,
    IntegrationStatus,
    NotificationSettings,
    NotificationSettingsUpdate,
    TeamMemberResponse,
    UserProfileResponse,
    UserProfileUpdate,
)
from app.services.exceptions import ValidationError as ServiceValidationError
from app.services.field_service.neighbor_outreach_config import (
    SETTINGS_KEY as NEIGHBOR_OUTREACH_KEY,
)
from app.services.field_service.neighbor_outreach_config import (
    get_neighbor_outreach_config,
)
from app.services.lead_sources.capture_settings import (
    SETTINGS_KEY as LEAD_SOURCE_CAPTURE_KEY,
)
from app.services.lead_sources.capture_settings import get_lead_source_capture_settings
from app.services.opportunities.lead_opportunity import (
    SETTINGS_KEY as AUTO_PIPELINE_KEY,
)
from app.services.opportunities.lead_opportunity import auto_pipeline_enabled
from app.services.opportunities.lifecycle_config import (
    SETTINGS_KEY as DEAL_LIFECYCLE_KEY,
)
from app.services.opportunities.lifecycle_config import (
    get_deal_lifecycle_config,
    validate_deal_lifecycle_references,
)
from app.services.opportunities.quote_opportunity import on_quote_sent_enabled
from app.services.quotes.attach_rules_config import (
    SETTINGS_KEY as ATTACH_RULES_KEY,
)
from app.services.quotes.attach_rules_config import (
    get_attach_rules_config,
)
from app.services.quotes.followup_config import (
    SETTINGS_KEY as QUOTE_FOLLOWUP_KEY,
)
from app.services.quotes.followup_config import get_quote_followup_config
from app.services.quotes.pricing_config import (
    SETTINGS_KEY as PRICING_KEY,
)
from app.services.quotes.pricing_config import (
    get_pricing_config,
)
from app.services.quotes.proposal_template import (
    SETTINGS_KEY as PROPOSAL_TEMPLATE_KEY,
)
from app.services.quotes.proposal_template import (
    get_proposal_template,
)
from app.services.quotes.revival_config import (
    SETTINGS_KEY as QUOTE_REVIVAL_KEY,
)
from app.services.quotes.revival_config import get_quote_revival_config
from app.services.sla.speed_to_lead import (
    SETTINGS_KEY as SPEED_TO_LEAD_KEY,
)
from app.services.sla.speed_to_lead import (
    compute_sla_metrics,
    get_speed_to_lead_settings,
)
from app.services.telephony.missed_call_textback import (
    SETTINGS_KEY as MISSED_CALL_TEXTBACK_KEY,
)

router = APIRouter()

# Notification preference attributes exposed via the settings API. Keeping a
# single list keeps the GET/PUT handlers and the response builder in sync.
_NOTIFICATION_PREF_FIELDS = (
    "notification_email",
    "notification_sms",
    "notification_push",
    "notification_push_calls",
    "notification_push_messages",
    "notification_push_voicemail",
    "notification_push_appointments",
    "notification_push_reviews",
    "notification_push_deal_alerts",
    "notification_push_missed_call_textback",
    "notification_push_roleplay",
    "notification_push_automations",
    "notification_push_new_lead",
)


def _notification_settings(user: object) -> NotificationSettings:
    """Build a NotificationSettings response from a user's preference columns."""
    return NotificationSettings(
        **{field: getattr(user, field) for field in _NOTIFICATION_PREF_FIELDS}
    )


# Known integration types with display names and descriptions
KNOWN_INTEGRATIONS = [
    {
        "integration_type": "telnyx",
        "display_name": "Telnyx",
        "description": "Voice & SMS provider",
    },
    {
        "integration_type": "resend",
        "display_name": "Resend",
        "description": "Email delivery",
    },
    {
        "integration_type": "openai",
        "display_name": "OpenAI",
        "description": "AI models for agents",
    },
    {
        "integration_type": "meta_lead_ads",
        "display_name": "Meta Lead Ads",
        "description": "Real-time Facebook and Instagram Instant Form leads",
    },
    {
        "integration_type": "lob",
        "display_name": "Lob",
        "description": "Physical card & postcard mailing",
    },
    {
        "integration_type": "quo",
        "display_name": "Quo",
        "description": "Business phone and messaging",
    },
    {
        "integration_type": "companycam",
        "display_name": "CompanyCam",
        "description": "Job photos attached to your contacts",
    },
]


@router.get("/users/me/profile", response_model=UserProfileResponse)
async def get_profile(current_user: CurrentUser) -> UserProfileResponse:
    """Get current user's profile."""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone_number=current_user.phone_number,
        timezone=current_user.timezone,
        avatar_url=current_user.avatar_url,
        created_at=current_user.created_at,
    )


@router.put("/users/me/profile", response_model=UserProfileResponse)
async def update_profile(
    profile_update: UserProfileUpdate,
    current_user: CurrentUser,
    db: DB,
) -> UserProfileResponse:
    """Update current user's profile."""
    if profile_update.full_name is not None:
        current_user.full_name = profile_update.full_name
    if profile_update.phone_number is not None:
        current_user.phone_number = profile_update.phone_number
    if profile_update.timezone is not None:
        current_user.timezone = profile_update.timezone
    if profile_update.avatar_url is not None:
        current_user.avatar_url = profile_update.avatar_url

    await db.commit()
    await db.refresh(current_user)

    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone_number=current_user.phone_number,
        timezone=current_user.timezone,
        avatar_url=current_user.avatar_url,
        created_at=current_user.created_at,
    )


@router.get("/users/me/notifications", response_model=NotificationSettings)
async def get_notifications(current_user: CurrentUser) -> NotificationSettings:
    """Get current user's notification settings."""
    return _notification_settings(current_user)


@router.put("/users/me/notifications", response_model=NotificationSettings)
async def update_notifications(
    notification_update: NotificationSettingsUpdate,
    current_user: CurrentUser,
    db: DB,
) -> NotificationSettings:
    """Update current user's notification settings."""
    updates = notification_update.model_dump(exclude_unset=True)
    for field in _NOTIFICATION_PREF_FIELDS:
        if updates.get(field) is not None:
            setattr(current_user, field, updates[field])

    await db.commit()
    await db.refresh(current_user)

    return _notification_settings(current_user)


@router.get("/workspaces/{workspace_id}/integrations", response_model=IntegrationsResponse)
async def get_integrations(
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageWorkspace,
) -> IntegrationsResponse:
    """Get workspace integration statuses."""
    integrations_result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace.id,
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    existing_integrations = {wi.integration_type for wi in integrations_result.scalars().all()}

    # Build response with known integrations
    integrations = []
    for known in KNOWN_INTEGRATIONS:
        integrations.append(
            IntegrationStatus(
                integration_type=known["integration_type"],
                is_connected=known["integration_type"] in existing_integrations,
                display_name=known["display_name"],
                description=known["description"],
            )
        )

    return IntegrationsResponse(integrations=integrations)


@router.get("/workspaces/{workspace_id}/team", response_model=list[TeamMemberResponse])
async def get_team_members(
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageMembers,
) -> list[TeamMemberResponse]:
    """Get workspace team members."""
    result = await db.execute(
        select(WorkspaceMembership)
        .join(User, User.id == WorkspaceMembership.user_id)
        .options(selectinload(WorkspaceMembership.user))
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            User.is_active.is_(True),
        )
    )
    memberships = result.scalars().all()
    user_ids = [membership.user_id for membership in memberships]
    bookable_user_ids: set[int] = set()
    calendar_connections: dict[int, str] = {}
    if user_ids:
        bookable_result = await db.execute(
            select(BookableStaff.user_id).where(
                BookableStaff.workspace_id == workspace.id,
                BookableStaff.user_id.in_(user_ids),
                BookableStaff.is_active.is_(True),
            )
        )
        bookable_user_ids = {
            user_id for user_id in bookable_result.scalars().all() if user_id is not None
        }
        calendar_result = await db.execute(
            select(
                GoogleCalendarConnection.user_id,
                GoogleCalendarConnection.google_email,
            ).where(GoogleCalendarConnection.user_id.in_(user_ids))
        )
        calendar_connections = dict(calendar_result.tuples().all())

    return [
        TeamMemberResponse(
            id=m.user.id,
            email=m.user.email,
            full_name=m.user.full_name,
            avatar_url=m.user.avatar_url,
            role=m.role,
            is_bookable=m.user_id in bookable_user_ids,
            google_calendar_connected=m.user_id in calendar_connections,
            google_calendar_email=calendar_connections.get(m.user_id),
            created_at=m.created_at,
        )
        for m in memberships
    ]


@router.get("/workspaces/{workspace_id}/business-hours", response_model=BusinessHoursSettings)
async def get_business_hours(
    workspace: WorkspaceAccess,
    _gate: CanManageWorkspace,
) -> BusinessHoursSettings:
    """Get workspace business hours settings."""
    business_hours = workspace.settings.get("business_hours", {})
    return BusinessHoursSettings(**business_hours)


@router.put("/workspaces/{workspace_id}/business-hours", response_model=BusinessHoursSettings)
async def update_business_hours(
    update: BusinessHoursUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageWorkspace,
) -> BusinessHoursSettings:
    """Update workspace business hours settings."""
    current_settings = dict(workspace.settings)
    business_hours = current_settings.get("business_hours", {})

    update_data = update.model_dump(exclude_unset=True)
    if "schedule" in update_data and update.schedule is not None:
        # Convert DaySchedule models to dicts
        update_data["schedule"] = {
            day: sched.model_dump() for day, sched in update.schedule.items()
        }
    business_hours.update(update_data)
    current_settings["business_hours"] = business_hours
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return BusinessHoursSettings(**workspace.settings.get("business_hours", {}))


@router.get(
    "/workspaces/{workspace_id}/proposal-template",
    response_model=ProposalTemplateSettings,
)
async def get_proposal_template_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadBilling,
) -> ProposalTemplateSettings:
    """Get the workspace's client-proposal branding + boilerplate template."""
    return get_proposal_template(workspace)


@router.put(
    "/workspaces/{workspace_id}/proposal-template",
    response_model=ProposalTemplateSettings,
)
async def update_proposal_template_settings(
    update: ProposalTemplateUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteBilling,
) -> ProposalTemplateSettings:
    """Update the proposal template (partial merge into ``workspace.settings``).

    Only provided keys are written, so editing one field never clobbers the
    others. This is the self-serve extensibility layer: the client proposal page
    re-renders from these values with no code change.
    """
    current_settings = dict(workspace.settings)
    template = dict(current_settings.get(PROPOSAL_TEMPLATE_KEY, {}))
    template.update(update.model_dump(exclude_unset=True))
    current_settings[PROPOSAL_TEMPLATE_KEY] = template
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return get_proposal_template(workspace)


async def _validate_bistro_inventory_mappings(
    db: AsyncSession, workspace_id: uuid.UUID, bistro: BistroConfig
) -> None:
    permanent_skus = {
        sku
        for sku in (
            bistro.permanent.lights_inventory_sku,
            bistro.permanent.poles_inventory_sku,
        )
        if sku
    }
    temporary_skus = {
        sku
        for sku in (
            bistro.temporary.lights_inventory_sku,
            bistro.temporary.poles_inventory_sku,
        )
        if sku
    }
    conflicting = sorted(permanent_skus & temporary_skus)
    if conflicting:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "A Bistro SKU cannot be both consumable and reusable",
                "conflicting_skus": conflicting,
            },
        )
    requested = permanent_skus | temporary_skus
    if not requested:
        return
    active_skus = set(
        (
            await db.execute(
                select(InventoryItem.sku).where(
                    InventoryItem.workspace_id == workspace_id,
                    InventoryItem.is_active.is_(True),
                    InventoryItem.sku.in_(requested),
                )
            )
        )
        .scalars()
        .all()
    )
    missing = sorted(requested - active_skus)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Every Bistro inventory SKU must be an active workspace item",
                "missing_skus": missing,
            },
        )


@router.get(
    "/workspaces/{workspace_id}/pricing",
    response_model=PricingSettings,
)
async def get_pricing_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadBilling,
) -> PricingSettings:
    """Get the workspace's sales-pricing config (the proposal engine)."""
    return get_pricing_config(workspace)


@router.put(
    "/workspaces/{workspace_id}/pricing",
    response_model=PricingSettings,
)
async def update_pricing_settings(
    update: PricingSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteBilling,
) -> PricingSettings:
    """Update the pricing config (shallow top-level merge into ``settings``).

    Only provided blocks are written, so editing ``financing`` never clobbers
    ``tiers``. A provided block replaces that whole block (validated at the edge).
    This is the "fork the data" boundary: a second lighting business clones this
    config and tweaks a few blocks with no code change.
    """
    if update.bistro is not None:
        await _validate_bistro_inventory_mappings(db, workspace.id, update.bistro)
    current_settings = dict(workspace.settings)
    config = dict(current_settings.get(PRICING_KEY, {}))
    config.update(update.model_dump(exclude_unset=True))
    current_settings[PRICING_KEY] = config
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return get_pricing_config(workspace)


@router.get(
    "/workspaces/{workspace_id}/neighbor-outreach",
    response_model=NeighborOutreachSettings,
)
async def get_neighbor_outreach_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> NeighborOutreachSettings:
    """Get the workspace's job-site neighbour-outreach config."""
    return get_neighbor_outreach_config(workspace)


@router.put(
    "/workspaces/{workspace_id}/neighbor-outreach",
    response_model=NeighborOutreachSettings,
)
async def update_neighbor_outreach_settings(
    update: NeighborOutreachSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteOutreach,
) -> NeighborOutreachSettings:
    """Update the neighbour-outreach config (partial merge into ``settings``).

    Only provided keys are written, so changing ``radius_meters`` never clobbers
    ``message_template_id``. The merged blob is validated before it is persisted — a
    stored config that no longer parses would silently fall back to "disabled", so
    a bad radius must fail loudly at the edit instead.

    ``message_template_id`` is checked to belong to this workspace: a template id is
    an opaque UUID, and pointing neighbour messaging at another tenant's copy would
    leak their copy to your customers.
    """
    current_settings = dict(workspace.settings or {})
    raw_config = current_settings.get(NEIGHBOR_OUTREACH_KEY, {})
    config_data = dict(raw_config) if isinstance(raw_config, dict) else {}
    config_data.update(update.model_dump(exclude_unset=True, mode="json"))
    try:
        config = NeighborOutreachSettings(**config_data)
    except PydanticValidationError as exc:
        # The merged config — not the raw request body — is what must stay valid, so
        # this validation runs after FastAPI's own and needs its own 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(error["msg"] for error in exc.errors()),
        ) from exc

    if config.message_template_id is not None:
        await _assert_templates_owned(
            {config.message_template_id}, workspace_id=workspace.id, db=db
        )

    current_settings[NEIGHBOR_OUTREACH_KEY] = config.model_dump(mode="json")
    workspace.settings = current_settings
    await db.commit()
    await db.refresh(workspace)
    return get_neighbor_outreach_config(workspace)


async def _assert_templates_owned(
    template_ids: set[uuid.UUID],
    *,
    workspace_id: uuid.UUID,
    db: DB,
) -> None:
    """Reject templates from another workspace before they are ever rendered.

    Template ids arrive as opaque UUIDs, so without this an operator could point
    a cadence at another tenant's copy and leak it to their own customers.
    """
    if not template_ids:
        return
    result = await db.execute(
        select(MessageTemplate.id).where(
            MessageTemplate.workspace_id == workspace_id,
            MessageTemplate.id.in_(template_ids),
        )
    )
    if set(result.scalars().all()) != template_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Every message template must belong to this workspace",
        )


@router.get(
    "/workspaces/{workspace_id}/post-estimate-followup",
    response_model=QuoteFollowupSettings,
)
async def get_quote_followup_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> QuoteFollowupSettings:
    """Get the workspace's first-14-days quote follow-up cadence."""
    return get_quote_followup_config(workspace)


@router.put(
    "/workspaces/{workspace_id}/post-estimate-followup",
    response_model=QuoteFollowupSettings,
)
async def update_quote_followup_settings(
    update: QuoteFollowupSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteOutreach,
) -> QuoteFollowupSettings:
    """Merge and validate the quote cadence inside ``workspace.settings``."""
    current_settings = dict(workspace.settings or {})
    raw_config = current_settings.get(QUOTE_FOLLOWUP_KEY, {})
    config_data = dict(raw_config) if isinstance(raw_config, dict) else {}
    config_data.update(update.model_dump(exclude_unset=True, mode="json"))
    try:
        config = QuoteFollowupSettings(**config_data)
    except PydanticValidationError as exc:
        # The merged cadence — not the raw request body — is what must stay valid,
        # so this validation runs after FastAPI's own and needs its own 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(error["msg"] for error in exc.errors()),
        ) from exc

    automated_without_templates = [
        touch.offset_days
        for touch in config.touches
        if touch.channel in {"sms", "email"} and touch.template_id is None
    ]
    if config.enabled and automated_without_templates:
        offsets = ", ".join(str(offset) for offset in automated_without_templates)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Automated touches on day(s) {offsets} need saved message templates",
        )

    await _assert_templates_owned(
        {touch.template_id for touch in config.touches if touch.template_id is not None},
        workspace_id=workspace.id,
        db=db,
    )

    current_settings[QUOTE_FOLLOWUP_KEY] = config.model_dump(mode="json")
    workspace.settings = current_settings
    await db.commit()
    await db.refresh(workspace)
    return get_quote_followup_config(workspace)


@router.get(
    "/workspaces/{workspace_id}/unsold-quote-revival",
    response_model=QuoteRevivalSettings,
)
async def get_quote_revival_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> QuoteRevivalSettings:
    """Get the workspace's 30/60/90-day unsold-quote revival ladder."""
    return get_quote_revival_config(workspace)


@router.put(
    "/workspaces/{workspace_id}/unsold-quote-revival",
    response_model=QuoteRevivalSettings,
)
async def update_quote_revival_settings(
    update: QuoteRevivalSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteOutreach,
) -> QuoteRevivalSettings:
    """Merge and validate the revival ladder inside ``workspace.settings``."""
    current_settings = dict(workspace.settings or {})
    raw_config = current_settings.get(QUOTE_REVIVAL_KEY, {})
    config_data = dict(raw_config) if isinstance(raw_config, dict) else {}
    config_data.update(update.model_dump(exclude_unset=True, mode="json"))
    try:
        config = QuoteRevivalSettings(**config_data)
    except PydanticValidationError as exc:
        # The merged ladder — not the raw request body — is what must stay
        # valid, so this validation runs after FastAPI's own and needs its 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(error["msg"] for error in exc.errors()),
        ) from exc

    # Only the touches that can actually run need copy: capping ``max_touches``
    # at 2 must not force an operator to configure a third template first.
    executable = config.touches[: config.max_touches]
    automated_without_templates = [
        touch.offset_days
        for touch in executable
        if touch.channel in {"sms", "email"} and touch.template_id is None
    ]
    if config.enabled and automated_without_templates:
        offsets = ", ".join(str(offset) for offset in automated_without_templates)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Automated touches on day(s) {offsets} need saved message templates",
        )

    await _assert_templates_owned(
        {
            template_id
            for touch in config.touches
            for template_id in (touch.template_id, touch.high_value_template_id)
            if template_id is not None
        },
        workspace_id=workspace.id,
        db=db,
    )

    current_settings[QUOTE_REVIVAL_KEY] = config.model_dump(mode="json")
    workspace.settings = current_settings
    await db.commit()
    await db.refresh(workspace)
    return get_quote_revival_config(workspace)


@router.get(
    "/workspaces/{workspace_id}/lead-source-capture",
    response_model=LeadSourceCaptureSettings,
)
async def get_lead_source_capture_policy(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> LeadSourceCaptureSettings:
    """Get the operator-only lead-source requirement for manual intake."""
    return get_lead_source_capture_settings(workspace)


@router.put(
    "/workspaces/{workspace_id}/lead-source-capture",
    response_model=LeadSourceCaptureSettings,
)
async def update_lead_source_capture_policy(
    update: LeadSourceCaptureSettings,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteCRM,
) -> LeadSourceCaptureSettings:
    """Replace the namespaced manual-intake policy without touching other settings."""
    current_settings = dict(workspace.settings or {})
    current_settings[LEAD_SOURCE_CAPTURE_KEY] = update.model_dump()
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)
    return get_lead_source_capture_settings(workspace)


@router.get(
    "/workspaces/{workspace_id}/deal-lifecycle",
    response_model=DealLifecycleSettings,
)
async def get_deal_lifecycle_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> DealLifecycleSettings:
    """Get the workspace's pipeline roles and follow-up operator timing."""
    return get_deal_lifecycle_config(workspace)


@router.put(
    "/workspaces/{workspace_id}/deal-lifecycle",
    response_model=DealLifecycleSettings,
)
async def update_deal_lifecycle_settings(
    update: DealLifecycleSettings,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWritePipeline,
) -> DealLifecycleSettings:
    """Replace lifecycle settings after checking every referenced tenant resource."""
    try:
        await validate_deal_lifecycle_references(
            db,
            workspace_id=workspace.id,
            config=update,
        )
    except ServiceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.message,
        ) from exc

    current_settings = dict(workspace.settings or {})
    current_settings[DEAL_LIFECYCLE_KEY] = update.model_dump(mode="json")
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)
    return get_deal_lifecycle_config(workspace)


@router.get(
    "/workspaces/{workspace_id}/auto-pipeline",
    response_model=AutoPipelineSettings,
)
async def get_auto_pipeline_policy(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> AutoPipelineSettings:
    """Get what auto-opens or advances a card on the sales pipeline."""
    return _auto_pipeline_settings(workspace)


@router.put(
    "/workspaces/{workspace_id}/auto-pipeline",
    response_model=AutoPipelineSettings,
)
async def update_auto_pipeline_policy(
    update: AutoPipelineSettings,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWritePipeline,
) -> AutoPipelineSettings:
    """Replace the namespaced auto-pipeline policy without touching other settings."""
    current_settings = dict(workspace.settings or {})
    current_settings[AUTO_PIPELINE_KEY] = update.model_dump()
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)
    return _auto_pipeline_settings(workspace)


def _auto_pipeline_settings(workspace: Workspace) -> AutoPipelineSettings:
    """Read both auto-pipeline switches through their own default-bearing readers."""
    return AutoPipelineSettings(
        enabled=auto_pipeline_enabled(workspace),
        on_quote_sent=on_quote_sent_enabled(workspace),
    )


@router.get(
    "/workspaces/{workspace_id}/attach-rules",
    response_model=AttachRulesSettings,
)
async def get_attach_rules_settings(
    workspace: WorkspaceAccess,
    _gate: CanReadBilling,
) -> AttachRulesSettings:
    """Get the workspace's attach-rule config (the cross-sell prompt)."""
    return get_attach_rules_config(workspace)


@router.put(
    "/workspaces/{workspace_id}/attach-rules",
    response_model=AttachRulesSettings,
)
async def update_attach_rules_settings(
    update: AttachRulesSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteBilling,
) -> AttachRulesSettings:
    """Update the attach-rule config (shallow top-level merge into ``settings``).

    Only provided keys are written, so editing the prompt copy never clobbers the
    rules. A provided ``rules`` list replaces the whole list (validated at the
    edge), matching how the pricing config writes blocks wholesale.
    """
    current_settings = dict(workspace.settings)
    config = dict(current_settings.get(ATTACH_RULES_KEY, {}))
    config.update(update.model_dump(exclude_unset=True))
    current_settings[ATTACH_RULES_KEY] = config
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return get_attach_rules_config(workspace)


@router.get("/workspaces/{workspace_id}/call-forwarding", response_model=CallForwardingSettings)
async def get_call_forwarding(
    workspace: WorkspaceAccess,
    _gate: CanManageComms,
) -> CallForwardingSettings:
    """Get workspace call forwarding settings."""
    call_forwarding = workspace.settings.get("call_forwarding", {})
    return CallForwardingSettings(**call_forwarding)


@router.put("/workspaces/{workspace_id}/call-forwarding", response_model=CallForwardingSettings)
async def update_call_forwarding(
    update: CallForwardingUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanManageComms,
) -> CallForwardingSettings:
    """Update workspace call forwarding settings."""
    current_settings = dict(workspace.settings)
    call_forwarding = current_settings.get("call_forwarding", {})

    update_data = update.model_dump(exclude_unset=True)
    call_forwarding.update(update_data)
    current_settings["call_forwarding"] = call_forwarding
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return CallForwardingSettings(**workspace.settings.get("call_forwarding", {}))


@router.get(
    "/workspaces/{workspace_id}/speed-to-lead",
    response_model=SpeedToLeadSettingsResponse,
)
async def get_speed_to_lead(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> SpeedToLeadSettingsResponse:
    """Get workspace speed-to-lead SLA settings."""
    config = get_speed_to_lead_settings(workspace)
    return SpeedToLeadSettingsResponse(
        enabled=config.enabled,
        sla_seconds=config.sla_seconds,
        alert_enabled=config.alert_enabled,
        badge_enabled=config.badge_enabled,
        badge_window_days=config.badge_window_days,
    )


@router.put(
    "/workspaces/{workspace_id}/speed-to-lead",
    response_model=SpeedToLeadSettingsResponse,
)
async def update_speed_to_lead(
    update: SpeedToLeadSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteOutreach,
) -> SpeedToLeadSettingsResponse:
    """Update workspace speed-to-lead SLA settings."""
    current_settings = dict(workspace.settings)
    speed_to_lead = dict(current_settings.get(SPEED_TO_LEAD_KEY, {}))
    speed_to_lead.update(update.model_dump(exclude_unset=True))
    current_settings[SPEED_TO_LEAD_KEY] = speed_to_lead
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    config = get_speed_to_lead_settings(workspace)
    return SpeedToLeadSettingsResponse(
        enabled=config.enabled,
        sla_seconds=config.sla_seconds,
        alert_enabled=config.alert_enabled,
        badge_enabled=config.badge_enabled,
        badge_window_days=config.badge_window_days,
    )


@router.get(
    "/workspaces/{workspace_id}/speed-to-lead/metrics",
    response_model=SpeedToLeadMetrics,
)
async def get_speed_to_lead_metrics(
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanReadCRM,
) -> SpeedToLeadMetrics:
    """Get live first-response SLA metrics for the workspace."""
    config = get_speed_to_lead_settings(workspace)
    metrics = await compute_sla_metrics(
        db,
        workspace.id,
        sla_seconds=config.sla_seconds,
        window_days=config.badge_window_days,
    )
    return SpeedToLeadMetrics(
        window_days=metrics.window_days,
        sla_seconds=metrics.sla_seconds,
        leads_measured=metrics.leads_measured,
        within_sla=metrics.within_sla,
        pct_within_sla=metrics.pct_within_sla,
        avg_response_seconds=metrics.avg_response_seconds,
        median_response_seconds=metrics.median_response_seconds,
        fastest_response_seconds=metrics.fastest_response_seconds,
    )


@router.get(
    "/workspaces/{workspace_id}/missed-call-textback",
    response_model=MissedCallTextbackSettingsResponse,
)
async def get_missed_call_textback(
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
) -> MissedCallTextbackSettingsResponse:
    """Get workspace missed-call text-back settings."""
    raw = workspace.settings.get(MISSED_CALL_TEXTBACK_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    return MissedCallTextbackSettingsResponse(**raw)


@router.put(
    "/workspaces/{workspace_id}/missed-call-textback",
    response_model=MissedCallTextbackSettingsResponse,
)
async def update_missed_call_textback(
    update: MissedCallTextbackSettingsUpdate,
    workspace: WorkspaceAccess,
    db: DB,
    _gate: CanWriteOutreach,
) -> MissedCallTextbackSettingsResponse:
    """Update workspace missed-call text-back settings."""
    current_settings = dict(workspace.settings)
    textback = dict(current_settings.get(MISSED_CALL_TEXTBACK_KEY, {}))
    textback.update(update.model_dump(exclude_unset=True))
    current_settings[MISSED_CALL_TEXTBACK_KEY] = textback
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    refreshed = workspace.settings.get(MISSED_CALL_TEXTBACK_KEY, {})
    if not isinstance(refreshed, dict):
        refreshed = {}
    return MissedCallTextbackSettingsResponse(**refreshed)


@router.get("/workspaces/{workspace_id}/card-settings")
async def get_card_settings(
    workspace: WorkspaceAccess,
    db: DB,  # noqa: ARG001
    _gate: CanReadBilling,
) -> dict[str, str]:
    """Get card service sender address settings."""
    result: dict[str, str] = workspace.settings.get("card_service", {})
    return result


@router.put("/workspaces/{workspace_id}/card-settings")
async def update_card_settings(
    workspace: WorkspaceAccess,
    db: DB,
    body: dict[str, str],
    _gate: CanWriteBilling,
) -> dict[str, str]:
    """Update card service sender address."""
    settings = dict(workspace.settings)
    settings["card_service"] = body
    workspace.settings = settings
    await db.commit()
    return body
