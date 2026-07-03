"""Settings endpoints for user profile, notifications, and workspace integrations."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, WorkspaceAccess
from app.models.workspace import WorkspaceIntegration, WorkspaceMembership
from app.schemas.pricing import (
    PricingSettings,
    PricingSettingsUpdate,
)
from app.schemas.proposal import (
    ProposalTemplateSettings,
    ProposalTemplateUpdate,
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
)


def _notification_settings(user: object) -> NotificationSettings:
    """Build a NotificationSettings response from a user's preference columns."""
    return NotificationSettings(
        **{field: getattr(user, field) for field in _NOTIFICATION_PREF_FIELDS}
    )


# Known integration types with display names and descriptions
KNOWN_INTEGRATIONS = [
    {
        "integration_type": "calcom",
        "display_name": "Cal.com",
        "description": "Appointment scheduling",
    },
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
        "integration_type": "lob",
        "display_name": "Lob",
        "description": "Physical card & postcard mailing",
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
) -> list[TeamMemberResponse]:
    """Get workspace team members."""
    result = await db.execute(
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.user))
        .where(WorkspaceMembership.workspace_id == workspace.id)
    )
    memberships = result.scalars().all()

    return [
        TeamMemberResponse(
            id=m.user.id,
            email=m.user.email,
            full_name=m.user.full_name,
            avatar_url=m.user.avatar_url,
            role=m.role,
            created_at=m.created_at,
        )
        for m in memberships
    ]


@router.get("/workspaces/{workspace_id}/business-hours", response_model=BusinessHoursSettings)
async def get_business_hours(
    workspace: WorkspaceAccess,
) -> BusinessHoursSettings:
    """Get workspace business hours settings."""
    business_hours = workspace.settings.get("business_hours", {})
    return BusinessHoursSettings(**business_hours)


@router.put("/workspaces/{workspace_id}/business-hours", response_model=BusinessHoursSettings)
async def update_business_hours(
    update: BusinessHoursUpdate,
    workspace: WorkspaceAccess,
    db: DB,
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


@router.get(
    "/workspaces/{workspace_id}/pricing",
    response_model=PricingSettings,
)
async def get_pricing_settings(
    workspace: WorkspaceAccess,
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
) -> PricingSettings:
    """Update the pricing config (shallow top-level merge into ``settings``).

    Only provided blocks are written, so editing ``financing`` never clobbers
    ``tiers``. A provided block replaces that whole block (validated at the edge).
    This is the "fork the data" boundary: a second lighting business clones this
    config and tweaks a few blocks with no code change.
    """
    current_settings = dict(workspace.settings)
    config = dict(current_settings.get(PRICING_KEY, {}))
    config.update(update.model_dump(exclude_unset=True))
    current_settings[PRICING_KEY] = config
    workspace.settings = current_settings

    await db.commit()
    await db.refresh(workspace)

    return get_pricing_config(workspace)


@router.get("/workspaces/{workspace_id}/call-forwarding", response_model=CallForwardingSettings)
async def get_call_forwarding(
    workspace: WorkspaceAccess,
) -> CallForwardingSettings:
    """Get workspace call forwarding settings."""
    call_forwarding = workspace.settings.get("call_forwarding", {})
    return CallForwardingSettings(**call_forwarding)


@router.put("/workspaces/{workspace_id}/call-forwarding", response_model=CallForwardingSettings)
async def update_call_forwarding(
    update: CallForwardingUpdate,
    workspace: WorkspaceAccess,
    db: DB,
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
) -> dict[str, str]:
    """Get card service sender address settings."""
    result: dict[str, str] = workspace.settings.get("card_service", {})
    return result


@router.put("/workspaces/{workspace_id}/card-settings")
async def update_card_settings(
    workspace: WorkspaceAccess, db: DB, body: dict[str, str]
) -> dict[str, str]:
    """Update card service sender address."""
    settings = dict(workspace.settings)
    settings["card_service"] = body
    workspace.settings = settings
    await db.commit()
    return body
