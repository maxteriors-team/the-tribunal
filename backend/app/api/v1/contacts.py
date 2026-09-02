"""Contact endpoints.

Access is capability-gated via :mod:`app.core.permissions`: reads require
``crm:read`` and record mutations require ``crm:write``. The one exception is
``POST /{contact_id}/messages`` — sending a text to the contact — which requires
``comms:send`` (it is messaging, not record editing), so field techs and sales
can reach customers without being able to edit the CRM. The gating dependency
also resolves workspace membership, replacing the old ``get_workspace`` check;
``workspace_id`` (the path param) is the workspace identifier used throughout.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select

from app.api.deps import (
    DB,
    CanReadCRM,
    CanSendComms,
    CanWriteCRM,
    CurrentUser,
    WorkspaceAccess,
)
from app.api.service_errors import ServiceErrorRoute
from app.core.config import settings
from app.core.encryption import hash_phone
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.lead_source import LeadSource
from app.models.message_attachment import (
    MESSAGE_ATTACHMENT_FAILED,
    MESSAGE_ATTACHMENT_READY,
    MessageAttachment,
)
from app.models.referral_partner import ReferralPartner
from app.schemas.contact import (
    AIToggleRequest,
    AIToggleResponse,
    BatchQualifyResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkStatusUpdateRequest,
    BulkStatusUpdateResponse,
    ContactAgentAssignRequest,
    ContactAgentAssignResponse,
    ContactAIKnowledgeResponse,
    ContactAIMemoryValueUpdate,
    ContactCreate,
    ContactEngagementSummary,
    ContactIdsResponse,
    ContactListResponse,
    ContactNoteCreate,
    ContactResponse,
    ContactStatsResponse,
    ContactUpdate,
    CSVPreviewResponse,
    ImportResult,
    ManualContactCreate,
    MessageResponse,
    QualificationSignals,
    QualifyContactResponse,
    SendMessageToContactRequest,
    TimelineItem,
)
from app.schemas.job_costing import ContactJobTimeSummaryResponse
from app.schemas.lead_source import AssignLeadSourceRequest, LeadAttributionFields
from app.services.ai.contact_ai_memory_service import ContactAIMemoryService
from app.services.contacts import (
    ContactAIStateService,
    ContactBulkService,
    ContactImportService,
    ContactQueryService,
    ContactService,
    ContactTimelineService,
)
from app.services.contacts.ai_knowledge_service import ContactAIKnowledgeService
from app.services.contacts.engagement_summary import get_engagement_summary
from app.services.contacts.exceptions import (
    ContactNotFoundError,
)
from app.services.dashboard.dashboard_service import invalidate_dashboard_cache
from app.services.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.services.jobs.costing_service import JobCostingService
from app.services.lead_sources.attribution_service import (
    MANUAL_ASSIGNMENT_CONFIDENCE,
    AttributionCleanupError,
    AttributionCleanupService,
)
from app.services.lead_sources.capture_settings import get_lead_source_capture_settings
from app.services.messaging.media_storage import MMSMediaStorage, MMSStorageError
from app.services.quo.line import (
    get_active_quo_line,
    visible_conversation_provider_clause,
)

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    sort_by: str | None = Query(
        None, description="Sort by: created_at, last_conversation, unread_first"
    ),
    # Advanced filters
    tags: str | None = Query(None, description="Comma-separated tag UUIDs"),
    tags_match: str = Query("any", description="Tag match mode: any, all, none"),
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    is_qualified: bool | None = None,
    source_filter: str | None = Query(None, alias="source"),
    company_name_filter: str | None = Query(None, alias="company_name"),
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    enrichment_status: str | None = None,
    filters: str | None = Query(None, description="JSON FilterDefinition"),
) -> ContactListResponse:
    """List contacts in a workspace."""
    service = ContactQueryService(db)
    try:
        result = await service.list_contacts(
            workspace_id=workspace_id,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            search=search,
            sort_by=sort_by,
            tags=tags,
            tags_match=tags_match,
            lead_score_min=lead_score_min,
            lead_score_max=lead_score_max,
            is_qualified=is_qualified,
            source=source_filter,
            company_name=company_name_filter,
            created_after=created_after,
            created_before=created_before,
            enrichment_status=enrichment_status,
            filters=filters,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return ContactListResponse(**result)


@router.get("/ids", response_model=ContactIdsResponse)
async def list_contact_ids(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = None,
    # Advanced filters
    tags: str | None = Query(None, description="Comma-separated tag UUIDs"),
    tags_match: str = Query("any", description="Tag match mode: any, all, none"),
    lead_score_min: int | None = None,
    lead_score_max: int | None = None,
    is_qualified: bool | None = None,
    source_filter: str | None = Query(None, alias="source"),
    company_name_filter: str | None = Query(None, alias="company_name"),
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    enrichment_status: str | None = None,
    filters: str | None = Query(None, description="JSON FilterDefinition"),
) -> ContactIdsResponse:
    """List all contact IDs matching filters."""
    service = ContactQueryService(db)
    try:
        result = await service.list_contact_ids(
            workspace_id=workspace_id,
            status_filter=status_filter,
            search=search,
            tags=tags,
            tags_match=tags_match,
            lead_score_min=lead_score_min,
            lead_score_max=lead_score_max,
            is_qualified=is_qualified,
            source=source_filter,
            company_name=company_name_filter,
            created_after=created_after,
            created_before=created_before,
            enrichment_status=enrichment_status,
            filters=filters,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return ContactIdsResponse(**result)


# Registered before `/{contact_id}` so FastAPI matches the static "stats" path
# instead of treating "stats" as a contact id (which would 422 on int parsing).
@router.get("/stats", response_model=ContactStatsResponse)
async def get_contact_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ContactStatsResponse:
    """Return aggregate contact metrics for the Contacts page stat cards."""
    service = ContactQueryService(db)
    result = await service.get_stats(workspace_id=workspace_id)
    return ContactStatsResponse(**result)


async def _create_contact_record(
    *,
    workspace_id: uuid.UUID,
    contact_in: ContactCreate,
    db: Any,
    attribution_fields: dict[str, Any] | None = None,
) -> Contact:
    """Forward one validated contact payload into the shared service."""
    service = ContactService(db)
    if attribution_fields is None:
        attribution_fields = contact_in.model_dump(
            include=set(LeadAttributionFields.model_fields), exclude_none=True
        )

    # Mailing address + avatar are accepted by the schema but aren't named
    # params on the service; forward them like attribution_fields, or they'd
    # be silently dropped on create (update never dropped them).
    profile_fields = contact_in.model_dump(
        include={
            "avatar_url",
            "address_line1",
            "address_line2",
            "address_city",
            "address_state",
            "address_zip",
        },
        exclude_none=True,
    )
    return await service.create_contact(
        workspace_id=workspace_id,
        first_name=contact_in.first_name,
        last_name=contact_in.last_name,
        email=contact_in.email,
        phone_number=contact_in.phone_number,
        company_name=contact_in.company_name,
        contact_status=contact_in.status,
        tags=contact_in.tags,
        notes=contact_in.notes,
        source=contact_in.source,
        important_dates=contact_in.important_dates,
        attribution_fields=attribution_fields,
        profile_fields=profile_fields,
    )


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    workspace_id: uuid.UUID,
    contact_in: ContactCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> Contact:
    """Create a contact through the general API/automation ingestion path.

    Workspace manual-intake policy is intentionally not consulted here: API,
    webhook, import, and other automated ingestion must remain non-breaking.
    """
    return await _create_contact_record(workspace_id=workspace_id, contact_in=contact_in, db=db)


@router.post("/manual", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact_manually(
    workspace_id: uuid.UUID,
    contact_in: ManualContactCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
    workspace: WorkspaceAccess,
) -> Contact:
    """Create an operator-entered contact and enforce only the manual policy."""
    capture_settings = get_lead_source_capture_settings(workspace)
    lead_source_id = contact_in.lead_source_id

    if capture_settings.require_lead_source_on_manual_create and lead_source_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Lead source is required for manually created contacts",
        )

    attribution_fields: dict[str, Any] = {}
    if lead_source_id is not None:
        lead_source = await db.get(LeadSource, lead_source_id)
        if (
            lead_source is None
            or lead_source.workspace_id != workspace_id
            or not lead_source.enabled
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Select an active lead source from this workspace",
            )

        captured_at = datetime.now(UTC)
        attribution_fields = {
            "first_touch_lead_source_id": lead_source_id,
            "first_touch_at": captured_at,
            "latest_touch_lead_source_id": lead_source_id,
            "latest_touch_at": captured_at,
            "attribution_confidence": MANUAL_ASSIGNMENT_CONFIDENCE,
        }

    # Who referred this lead is recorded whether or not a lead source was picked,
    # so a workspace that never configured lead sources still builds a partner
    # scoreboard. Validated in-tenant and active: crediting a retired or another
    # tenant's partner would silently corrupt the scoreboard.
    if contact_in.referral_partner_id is not None:
        partner = await db.get(ReferralPartner, contact_in.referral_partner_id)
        if partner is None or partner.workspace_id != workspace_id or not partner.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Select an active referral partner from this workspace",
            )
        attribution_fields["referral_partner_id"] = contact_in.referral_partner_id

    return await _create_contact_record(
        workspace_id=workspace_id,
        contact_in=contact_in,
        db=db,
        attribution_fields=attribution_fields,
    )


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> Contact:
    """Get a specific contact."""
    service = ContactService(db)
    try:
        return await service.get_contact(contact_id, workspace_id)
    except ContactNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{contact_id}/ai-knowledge", response_model=ContactAIKnowledgeResponse)
async def get_contact_ai_knowledge(
    workspace_id: uuid.UUID,
    contact_id: int,
    response: Response,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ContactAIKnowledgeResponse:
    """Return a data-minimized view instead of widening every contact response."""
    response.headers["Cache-Control"] = "private, no-store"
    knowledge = await ContactAIKnowledgeService(db).get_knowledge(
        workspace_id=workspace_id,
        contact_id=contact_id,
    )
    if knowledge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return knowledge


@router.put("/{contact_id}/ai-knowledge/summary", response_model=ContactAIKnowledgeResponse)
async def update_contact_ai_memory_summary(
    workspace_id: uuid.UUID,
    contact_id: int,
    update_in: ContactAIMemoryValueUpdate,
    response: Response,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> ContactAIKnowledgeResponse:
    """Correct or remove the generated summary; authoritative CRM fields are untouched."""
    response.headers["Cache-Control"] = "private, no-store"
    knowledge_service = ContactAIKnowledgeService(db)
    existing = await knowledge_service.get_knowledge(
        workspace_id=workspace_id,
        contact_id=contact_id,
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    if update_in.value is None and existing.memory_summary is None:
        return existing

    updated = await ContactAIMemoryService(db).update_summary(
        workspace_id=workspace_id,
        contact_id=contact_id,
        value=update_in.value,
        operator_id=current_user.id,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    await db.commit()

    knowledge = await knowledge_service.get_knowledge(
        workspace_id=workspace_id,
        contact_id=contact_id,
    )
    if knowledge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return knowledge


@router.put(
    "/{contact_id}/ai-knowledge/facts/{fact_id}",
    response_model=ContactAIKnowledgeResponse,
)
async def update_contact_ai_memory_fact(
    workspace_id: uuid.UUID,
    contact_id: int,
    fact_id: uuid.UUID,
    update_in: ContactAIMemoryValueUpdate,
    response: Response,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> ContactAIKnowledgeResponse:
    """Correct or remove one generated fact under the exact workspace/contact scope."""
    response.headers["Cache-Control"] = "private, no-store"
    knowledge_service = ContactAIKnowledgeService(db)
    existing = await knowledge_service.get_knowledge(
        workspace_id=workspace_id,
        contact_id=contact_id,
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")

    updated = await ContactAIMemoryService(db).update_fact(
        workspace_id=workspace_id,
        contact_id=contact_id,
        fact_id=fact_id,
        value=update_in.value,
        operator_id=current_user.id,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated memory fact not found",
        )
    await db.commit()

    knowledge = await knowledge_service.get_knowledge(
        workspace_id=workspace_id,
        contact_id=contact_id,
    )
    if knowledge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return knowledge


@router.post("/{contact_id}/notes", response_model=ContactResponse)
async def append_contact_note(
    workspace_id: uuid.UUID,
    contact_id: int,
    note_in: ContactNoteCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> Contact:
    """Append an internal client note without replacing prior note history."""
    service = ContactService(db)
    author_name = current_user.full_name or current_user.email
    try:
        return await service.append_contact_note(
            contact_id, workspace_id, note_in.body, author_name
        )
    except ContactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    workspace_id: uuid.UUID,
    contact_id: int,
    contact_in: ContactUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> Contact:
    """Update a contact."""
    service = ContactService(db)
    update_data = contact_in.model_dump(exclude_unset=True)
    try:
        return await service.update_contact(contact_id, workspace_id, update_data)
    except ContactNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> None:
    """Delete a contact."""
    service = ContactService(db)
    try:
        await service.delete_contact(contact_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_contacts(
    workspace_id: uuid.UUID,
    request: BulkDeleteRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> BulkDeleteResponse:
    """Delete multiple contacts at once."""
    service = ContactBulkService(db)
    try:
        result = await service.bulk_delete_contacts(request.ids, workspace_id)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return BulkDeleteResponse(**result)


@router.post("/bulk-update-status", response_model=BulkStatusUpdateResponse)
async def bulk_update_status(
    workspace_id: uuid.UUID,
    request: BulkStatusUpdateRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> BulkStatusUpdateResponse:
    """Update the status of multiple contacts at once."""
    service = ContactBulkService(db)
    try:
        result = await service.bulk_update_status(request.ids, workspace_id, request.status)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return BulkStatusUpdateResponse(**result)


@router.post("/{contact_id}/messages", response_model=MessageResponse)
async def send_message_to_contact(
    workspace_id: uuid.UUID,
    contact_id: int,
    message_in: SendMessageToContactRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
) -> Any:
    """Send an SMS message to a contact.

    This endpoint finds or creates a conversation for the contact and sends the message.
    """
    service = ContactService(db)
    try:
        return await service.send_message(
            contact_id=contact_id,
            workspace_id=workspace_id,
            message_body=message_in.body,
            from_number=message_in.from_number,
            image_data_url=message_in.image_data_url,
            sender_user_id=current_user.id,
            sender_display_name=current_user.full_name or current_user.email,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ServiceUnavailableError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{contact_id}/ai/toggle", response_model=AIToggleResponse)
async def toggle_contact_ai(
    workspace_id: uuid.UUID,
    contact_id: int,
    toggle_in: AIToggleRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> AIToggleResponse:
    """Toggle AI for a contact's conversation.

    Finds an existing conversation for the contact or creates one if needed.
    """
    service = ContactAIStateService(db)
    try:
        result = await service.toggle_ai(
            contact_id=contact_id,
            workspace_id=workspace_id,
            enabled=toggle_in.enabled,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return AIToggleResponse(**result)


@router.post("/{contact_id}/agent", response_model=ContactAgentAssignResponse)
async def assign_contact_agent(
    workspace_id: uuid.UUID,
    contact_id: int,
    assign_in: ContactAgentAssignRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> ContactAgentAssignResponse:
    """Assign an AI agent to the contact's active conversation."""
    service = ContactAIStateService(db)
    try:
        result = await service.assign_agent(
            contact_id=contact_id,
            workspace_id=workspace_id,
            agent_id=assign_in.agent_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return ContactAgentAssignResponse(**result)


@router.post("/{contact_id}/lead-source", status_code=status.HTTP_204_NO_CONTENT)
async def assign_contact_lead_source(
    workspace_id: uuid.UUID,
    contact_id: int,
    assign_in: AssignLeadSourceRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> None:
    """Manually attribute a lead source to a contact from the cleanup queue.

    Backfills the contact's touch fields and any still-unattributed
    opportunities so the correction flows through to canonical booked ROI.
    """
    service = AttributionCleanupService(db)
    try:
        await service.assign(
            workspace_id=workspace_id,
            contact_id=contact_id,
            lead_source_id=assign_in.lead_source_id,
            lead_source_campaign_id=assign_in.lead_source_campaign_id,
            source_type=assign_in.source_type,
            correct_existing=assign_in.correct_existing,
        )
    except AttributionCleanupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    # Backfilled opportunities change booked attribution — refresh ROI now.
    await invalidate_dashboard_cache(workspace_id)


@router.get("/{contact_id}/timeline", response_model=list[TimelineItem])
async def get_contact_timeline(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    limit: int = Query(100, ge=1, le=500),
    conversation_id: uuid.UUID | None = Query(default=None),
) -> list[TimelineItem]:
    """Get the conversation timeline for a contact.

    Returns a unified timeline of SMS messages, calls, appointments, etc.
    """
    if conversation_id is not None:
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact_id,
            )
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.source_provider == "quo":
            active_line = await get_active_quo_line(db, workspace_id)
            if active_line is None or conversation.workspace_phone_hash != hash_phone(
                active_line.phone_number
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )

    service = ContactTimelineService(db)
    timeline_items_data = await service.get_contact_timeline(
        contact_id=contact_id,
        workspace_id=workspace_id,
        limit=limit,
        conversation_id=conversation_id,
    )

    # Convert dicts to TimelineItem models
    return [TimelineItem(**item) for item in timeline_items_data]


@router.get(
    "/{contact_id}/timeline/attachments/{attachment_id}/content",
    response_class=RedirectResponse,
    responses={
        307: {"description": "Redirect to a short-lived private media URL"},
        404: {"description": "Attachment not found"},
        409: {"description": "Attachment is still processing"},
        410: {"description": "Attachment could not be processed"},
        503: {"description": "Private media storage is unavailable"},
    },
)
async def get_timeline_attachment_content(
    workspace_id: uuid.UUID,
    contact_id: int,
    attachment_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> RedirectResponse:
    """Authorize one contact attachment and redirect to a private object URL."""
    contact_result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.workspace_id == workspace_id,
        )
    )
    contact = contact_result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    conversation_matches = [Conversation.contact_id == contact_id]
    if contact.phone_number:
        conversation_matches.append(
            Conversation.contact_phone_hash == hash_phone(contact.phone_number)
        )

    visible_provider = await visible_conversation_provider_clause(db, workspace_id)
    attachment_result = await db.execute(
        select(MessageAttachment)
        .join(Message, MessageAttachment.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            MessageAttachment.id == attachment_id,
            MessageAttachment.workspace_id == workspace_id,
            Conversation.workspace_id == workspace_id,
            or_(*conversation_matches),
            visible_provider,
        )
    )
    attachment = attachment_result.scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.status == MESSAGE_ATTACHMENT_FAILED:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Attachment is unavailable",
        )
    if attachment.status != MESSAGE_ATTACHMENT_READY or not attachment.storage_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attachment is still processing",
        )

    try:
        storage = MMSMediaStorage.from_settings(settings)
        media_url = await asyncio.to_thread(
            storage.create_download_url,
            object_key=attachment.storage_key,
        )
    except MMSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attachment storage is unavailable",
        ) from exc

    return RedirectResponse(
        url=media_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get(
    "/{contact_id}/engagement-summary",
    response_model=ContactEngagementSummary,
)
async def get_contact_engagement_summary(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ContactEngagementSummary:
    """Return aggregated engagement stats for a contact."""
    service = ContactService(db)
    try:
        contact = await service.get_contact(contact_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    return await get_engagement_summary(
        db=db,
        contact=contact,
        workspace_id=workspace_id,
    )


@router.get(
    "/{contact_id}/job-time",
    response_model=ContactJobTimeSummaryResponse,
)
async def get_contact_job_time(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ContactJobTimeSummaryResponse:
    """Return saved job time on the client profile without labor pricing."""
    return await JobCostingService(db).get_contact_time_summary(contact_id, workspace_id)


# ============================================================================
# CSV Import
# ============================================================================


@router.post("/import/preview", response_model=CSVPreviewResponse)
async def preview_import_csv(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
    file: UploadFile,
) -> CSVPreviewResponse:
    """Preview a CSV file before importing.

    Returns the headers, sample rows, and suggested field mappings.
    """
    import_service = ContactImportService(db)
    try:
        preview = await import_service.preview_upload(file)
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return CSVPreviewResponse(**preview)


@router.post("/import", response_model=ImportResult)
async def import_contacts_csv(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
    file: UploadFile,
    skip_duplicates: bool = Form(default=True),
    default_status: str = Form(default="new"),
    source: str = Form(default="csv_import"),
    column_mapping: str | None = Form(default=None),
) -> ImportResult:
    """Import contacts from a CSV file.

    The CSV should have headers in the first row. Supported columns:
    - first_name (required): First name of the contact
    - last_name: Last name
    - email: Email address
    - phone_number (required): Phone number
    - company_name: Company or organization
    - status: Lead status (new, contacted, qualified, converted, lost)
    - tags: Comma-separated tags
    - notes: Additional notes

    Column names are case-insensitive and support common variations.
    """
    import_service = ContactImportService(db)
    try:
        result = await import_service.import_upload(
            workspace_id=workspace_id,
            file=file,
            skip_duplicates=skip_duplicates,
            default_status=default_status,
            source=source,
            column_mapping=column_mapping,
        )
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    # Convert to response format
    return ImportResult(
        total_rows=result.total_rows,
        successful=result.successful,
        failed=result.failed,
        skipped_duplicates=result.skipped_duplicates,
        errors=result.errors,
        created_contacts=[ContactResponse.model_validate(c) for c in result.created_contacts],
    )


@router.get("/import/template")
async def get_import_template(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> dict[str, Any]:
    """Get CSV import template information."""
    return ContactImportService.get_template_info()


# ============================================================================
# Lead Qualification
# ============================================================================


@router.post("/{contact_id}/qualify", response_model=QualifyContactResponse)
async def qualify_contact(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> QualifyContactResponse:
    """Analyze a contact's conversations and update their qualification status.

    Uses AI to extract BANT (Budget, Authority, Need, Timeline) signals from
    all conversations with the contact and calculates a lead score.

    The contact's is_qualified flag will be set to True if their score
    exceeds the qualification threshold (60).
    """
    from app.services.ai.qualification import analyze_and_qualify_contact

    # Verify contact exists in workspace
    result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.workspace_id == workspace_id,
        )
    )
    contact = result.scalar_one_or_none()

    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        )

    # Run qualification analysis
    analysis = await analyze_and_qualify_contact(contact_id, db)

    if not analysis.get("success"):
        return QualifyContactResponse(
            success=False,
            error=analysis.get("error", "Unknown error"),
        )

    # Convert signals dict to QualificationSignals model if present
    signals = None
    if analysis.get("qualification_signals"):
        signals = QualificationSignals(**analysis["qualification_signals"])

    return QualifyContactResponse(
        success=True,
        contact_id=analysis.get("contact_id"),
        lead_score=analysis.get("lead_score", 0),
        is_qualified=analysis.get("is_qualified", False),
        qualification_signals=signals,
        has_appointment=analysis.get("has_appointment", False),
        response_rate=analysis.get("response_rate", 0.0),
        message=analysis.get("message"),
    )


@router.get("/{contact_id}/qualification", response_model=QualifyContactResponse)
async def get_contact_qualification(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> QualifyContactResponse:
    """Get the current qualification status of a contact without re-analyzing."""
    # Get contact
    result = await db.execute(
        select(Contact).where(
            Contact.id == contact_id,
            Contact.workspace_id == workspace_id,
        )
    )
    contact = result.scalar_one_or_none()

    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found",
        )

    # Convert signals dict to QualificationSignals model if present
    signals = None
    if contact.qualification_signals:
        signals = QualificationSignals(**contact.qualification_signals)

    return QualifyContactResponse(
        success=True,
        contact_id=contact.id,
        lead_score=contact.lead_score,
        is_qualified=contact.is_qualified,
        qualification_signals=signals,
    )


@router.post("/qualify/batch", response_model=BatchQualifyResponse)
async def batch_qualify_contacts(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
    limit: int = Query(50, ge=1, le=100),
) -> BatchQualifyResponse:
    """Analyze and qualify multiple contacts in the workspace.

    Prioritizes contacts that:
    - Have never been analyzed
    - Are in 'new' or 'contacted' status

    This is useful for batch processing leads that need qualification.
    """
    from app.services.ai.qualification import batch_analyze_contacts

    # Run batch analysis
    result = await batch_analyze_contacts(str(workspace_id), db, limit)

    if not result.get("success"):
        return BatchQualifyResponse(
            success=False,
            error=result.get("error", "Unknown error"),
        )

    return BatchQualifyResponse(
        success=True,
        analyzed=result.get("analyzed", 0),
        qualified=result.get("qualified", 0),
        errors=result.get("errors", 0),
        contacts=result.get("contacts", []),
    )
