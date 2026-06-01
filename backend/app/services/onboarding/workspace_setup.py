"""Workspace setup workflows for realtor onboarding."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.scope import apply_workspace_scope
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignContact, CampaignStatus
from app.models.contact import Contact
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.agents.realtor_template import (
    get_realtor_agent_config,
    get_realtor_campaign_defaults,
)
from app.services.contacts import ContactImportService, ImportResult
from app.services.onboarding.credentials import (
    store_calcom_credentials,
    store_followupboss_credentials,
)
from app.services.onboarding.exceptions import OnboardingValidationError, OnboardingWorkspaceError
from app.services.reactivation.drip_bootstrap import auto_create_drip_for_imports
from app.services.telephony.telnyx import PhoneNumberInfo, TelnyxSMSService

logger = structlog.get_logger()

REALTOR_AGENT_NAME = "Realtor Lead Reactivation Agent"


@dataclass(slots=True, frozen=True)
class RealtorOnboardingInput:
    """Input values required to complete realtor workspace onboarding."""

    calcom_api_key: str
    calcom_event_type_id: int
    area_code: str | None = None
    fub_api_key: str | None = None


@dataclass(slots=True, frozen=True)
class RealtorOnboardingResult:
    """Result of realtor workspace onboarding."""

    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    phone_number_id: uuid.UUID | None
    phone_number: str | None
    calcom_connected: bool


@dataclass(slots=True, frozen=True)
class RealtorCampaignInput:
    """Input values required to import contacts and launch a realtor campaign."""

    file_content: bytes
    skip_duplicates: bool
    campaign_name: str | None = None


@dataclass(slots=True, frozen=True)
class RealtorCampaignResult:
    """Result of launching a realtor campaign from uploaded contacts."""

    campaign_id: uuid.UUID
    campaign_name: str
    campaign_status: str
    contacts_imported: int
    contacts_skipped: int
    contacts_failed: int
    phone_number_used: str
    agent_id: uuid.UUID
    started_at: datetime | None


@dataclass(slots=True, frozen=True)
class PhoneProvisioningResult:
    """Best-effort phone-number provisioning outcome."""

    phone_number_id: uuid.UUID | None
    phone_number: str | None


TelnyxServiceFactory = Callable[[str], TelnyxSMSService]
ContactImportServiceFactory = Callable[[AsyncSession], ContactImportService]
DripBootstrapper = Callable[[AsyncSession, uuid.UUID, list[int]], Awaitable[None]]


async def get_user_workspace(current_user_id: int, db: AsyncSession) -> Workspace:
    """Resolve a user's default workspace, falling back to their first membership."""
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == current_user_id,
            WorkspaceMembership.is_default.is_(True),
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        result = await db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == current_user_id)
            .order_by(WorkspaceMembership.created_at.asc())
            .limit(1)
        )
        membership = result.scalar_one_or_none()

    if membership is None:
        raise OnboardingWorkspaceError("No workspace found. Please create a workspace first.")

    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == membership.workspace_id,
            Workspace.is_active.is_(True),
        )
    )
    workspace = ws_result.scalar_one_or_none()

    if workspace is None:
        raise OnboardingWorkspaceError("Workspace not found or is inactive.")

    return workspace


async def complete_realtor_onboarding(
    *,
    db: AsyncSession,
    current_user_id: int,
    request: RealtorOnboardingInput,
    telnyx_api_key: str | None = None,
    telnyx_service_factory: TelnyxServiceFactory = TelnyxSMSService,
) -> RealtorOnboardingResult:
    """Create the realtor agent, store credentials, and best-effort provision SMS."""
    workspace = await get_user_workspace(current_user_id, db)
    workspace_id = workspace.id

    agent = await create_realtor_agent(
        db=db,
        workspace_id=workspace_id,
        calcom_event_type_id=request.calcom_event_type_id,
    )
    logger.info(
        "realtor_agent_created",
        workspace_id=str(workspace_id),
        agent_id=str(agent.id),
        user_id=current_user_id,
    )

    await store_calcom_credentials(db, workspace_id, request.calcom_api_key)
    logger.info(
        "calcom_integration_stored",
        workspace_id=str(workspace_id),
        user_id=current_user_id,
    )

    if request.fub_api_key:
        await store_followupboss_credentials(db, workspace_id, request.fub_api_key)
        logger.info(
            "fub_integration_stored",
            workspace_id=str(workspace_id),
            user_id=current_user_id,
        )

    phone = await provision_realtor_phone_number(
        db=db,
        workspace_id=workspace_id,
        area_code=request.area_code,
        telnyx_api_key=telnyx_api_key if telnyx_api_key is not None else settings.telnyx_api_key,
        telnyx_service_factory=telnyx_service_factory,
    )

    await db.commit()

    return RealtorOnboardingResult(
        workspace_id=workspace_id,
        agent_id=agent.id,
        phone_number_id=phone.phone_number_id,
        phone_number=phone.phone_number,
        calcom_connected=True,
    )


async def create_realtor_agent(
    *,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    calcom_event_type_id: int,
) -> Agent:
    """Create a realtor template text agent in the workspace."""
    agent_config = get_realtor_agent_config()
    agent = Agent(
        workspace_id=workspace_id,
        name=REALTOR_AGENT_NAME,
        calcom_event_type_id=calcom_event_type_id,
        **agent_config,
    )
    db.add(agent)
    await db.flush()
    return agent


async def provision_realtor_phone_number(
    *,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    area_code: str | None,
    telnyx_api_key: str | None,
    telnyx_service_factory: TelnyxServiceFactory = TelnyxSMSService,
) -> PhoneProvisioningResult:
    """Best-effort purchase and persist a Telnyx phone number for onboarding."""
    if not telnyx_api_key:
        logger.warning(
            "telnyx_not_configured_skipping_phone_purchase",
            workspace_id=str(workspace_id),
        )
        return PhoneProvisioningResult(phone_number_id=None, phone_number=None)

    telnyx = telnyx_service_factory(telnyx_api_key)
    try:
        available = await telnyx.search_phone_numbers(
            country="US",
            area_code=area_code,
            limit=5,
        )

        if not available:
            logger.warning(
                "no_available_phone_numbers",
                workspace_id=str(workspace_id),
                area_code=area_code,
            )
            return PhoneProvisioningResult(phone_number_id=None, phone_number=None)

        purchased = await telnyx.purchase_phone_number(available[0].phone_number)
        phone_record = _build_phone_number(workspace_id, purchased)
        db.add(phone_record)
        await db.flush()

        logger.info(
            "phone_number_provisioned",
            workspace_id=str(workspace_id),
            phone_number=purchased.phone_number,
        )
        return PhoneProvisioningResult(
            phone_number_id=phone_record.id,
            phone_number=purchased.phone_number,
        )
    except Exception as exc:  # best-effort provisioning must not fail onboarding
        logger.error(
            "phone_number_provisioning_failed",
            workspace_id=str(workspace_id),
            error=str(exc),
        )
        return PhoneProvisioningResult(phone_number_id=None, phone_number=None)
    finally:
        await telnyx.close()


def _build_phone_number(workspace_id: uuid.UUID, purchased: PhoneNumberInfo) -> PhoneNumber:
    """Build a PhoneNumber model for a purchased Telnyx number."""
    return PhoneNumber(
        workspace_id=workspace_id,
        phone_number=purchased.phone_number,
        telnyx_phone_number_id=purchased.id,
        sms_enabled=True,
        voice_enabled=True,
        is_active=True,
    )


async def launch_realtor_campaign_from_csv(
    *,
    db: AsyncSession,
    current_user_id: int,
    request: RealtorCampaignInput,
    import_service_factory: ContactImportServiceFactory = ContactImportService,
    drip_bootstrapper: DripBootstrapper = auto_create_drip_for_imports,
    now: Callable[[], datetime] | None = None,
) -> RealtorCampaignResult:
    """Import contacts from CSV, create a campaign, enroll contacts, and start it."""
    workspace = await get_user_workspace(current_user_id, db)
    workspace_id = workspace.id

    import_result = await import_realtor_contacts(
        db=db,
        workspace_id=workspace_id,
        file_content=request.file_content,
        skip_duplicates=request.skip_duplicates,
        import_service_factory=import_service_factory,
    )

    agent = await get_realtor_agent(db=db, workspace_id=workspace_id)
    phone_record = await get_realtor_sms_phone_number(db=db, workspace_id=workspace_id)
    clock = now or (lambda: datetime.now(UTC))
    campaign = await create_realtor_campaign(
        db=db,
        workspace_id=workspace_id,
        agent=agent,
        phone_record=phone_record,
        campaign_name=request.campaign_name,
        now=clock,
    )

    added_count = enroll_campaign_contacts(db, campaign, import_result.created_contacts)
    campaign.total_contacts = added_count
    campaign.status = CampaignStatus.RUNNING
    campaign.started_at = clock()

    drip_ids = [contact.id for contact in import_result.created_contacts]
    await drip_bootstrapper(db, workspace_id, drip_ids)

    await db.commit()
    await db.refresh(campaign)

    logger.info(
        "realtor_campaign_started",
        workspace_id=str(workspace_id),
        campaign_id=str(campaign.id),
        contacts=added_count,
    )

    return RealtorCampaignResult(
        campaign_id=campaign.id,
        campaign_name=campaign.name,
        campaign_status=campaign.status,
        contacts_imported=import_result.successful,
        contacts_skipped=import_result.skipped_duplicates,
        contacts_failed=import_result.failed,
        phone_number_used=phone_record.phone_number,
        agent_id=agent.id,
        started_at=campaign.started_at,
    )


async def import_realtor_contacts(
    *,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    file_content: bytes,
    skip_duplicates: bool,
    import_service_factory: ContactImportServiceFactory = ContactImportService,
) -> ImportResult:
    """Import realtor CSV contacts and map import failures to onboarding errors."""
    import_service = import_service_factory(db)
    try:
        import_result = await import_service.import_csv(
            workspace_id=workspace_id,
            file_content=file_content,
            skip_duplicates=skip_duplicates,
            source="realtor_csv_upload",
        )
    except ValueError as exc:
        raise OnboardingValidationError(str(exc)) from exc

    if not import_result.created_contacts:
        raise OnboardingValidationError(
            "No contacts were imported from the CSV. "
            f"Rows processed: {import_result.total_rows}, "
            f"failed: {import_result.failed}, "
            f"skipped: {import_result.skipped_duplicates}."
        )

    return import_result


async def get_realtor_agent(*, db: AsyncSession, workspace_id: uuid.UUID) -> Agent:
    """Return the realtor agent, falling back to the first text-channel agent."""
    agent_result = await db.execute(
        apply_workspace_scope(select(Agent), Agent, workspace_id)
        .where(Agent.name == REALTOR_AGENT_NAME)
        .limit(1)
    )
    agent = agent_result.scalar_one_or_none()

    if agent is None:
        fallback_result = await db.execute(
            apply_workspace_scope(select(Agent), Agent, workspace_id)
            .where(Agent.channel_mode == "text")
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
        agent = fallback_result.scalar_one_or_none()

    if agent is None:
        raise OnboardingValidationError(
            "No realtor agent found in this workspace. "
            "Complete onboarding first to create the agent."
        )

    return agent


async def get_realtor_sms_phone_number(*, db: AsyncSession, workspace_id: uuid.UUID) -> PhoneNumber:
    """Return the first active SMS-enabled phone number in the workspace."""
    phone_result = await db.execute(
        apply_workspace_scope(select(PhoneNumber), PhoneNumber, workspace_id)
        .where(
            PhoneNumber.is_active.is_(True),
            PhoneNumber.sms_enabled.is_(True),
        )
        .order_by(PhoneNumber.created_at.asc())
        .limit(1)
    )
    phone_record = phone_result.scalar_one_or_none()

    if phone_record is None:
        raise OnboardingValidationError(
            "No active SMS-enabled phone number found in this workspace. "
            "Complete onboarding first or add a phone number from Settings."
        )

    return phone_record


async def create_realtor_campaign(
    *,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    agent: Agent,
    phone_record: PhoneNumber,
    campaign_name: str | None,
    now: Callable[[], datetime],
) -> Campaign:
    """Create the Campaign row for a realtor lead-reactivation launch."""
    defaults = get_realtor_campaign_defaults()
    date_str = now().strftime("%B %d, %Y")
    resolved_name = campaign_name or f"Lead Reactivation - {date_str}"

    campaign = Campaign(
        workspace_id=workspace_id,
        agent_id=agent.id,
        from_phone_number=phone_record.phone_number,
        name=resolved_name,
        ai_enabled=True,
        **{key: value for key, value in defaults.items() if key not in ("name", "ai_enabled")},
    )
    db.add(campaign)
    await db.flush()

    logger.info(
        "realtor_campaign_created",
        workspace_id=str(workspace_id),
        campaign_id=str(campaign.id),
        agent_id=str(agent.id),
    )
    return campaign


def enroll_campaign_contacts(
    db: AsyncSession,
    campaign: Campaign,
    contacts: Sequence[Contact],
) -> int:
    """Create CampaignContact rows for imported contacts and return the count."""
    added_count = 0
    for contact in contacts:
        campaign_contact = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
        )
        db.add(campaign_contact)
        added_count += 1
    return added_count
