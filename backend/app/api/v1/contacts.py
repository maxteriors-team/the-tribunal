"""Contact endpoints.

Access is capability-gated via :mod:`app.core.permissions`: reads require
``crm:read`` and record mutations require ``crm:write``. The one exception is
``POST /{contact_id}/messages`` — sending a text to the contact — which requires
``comms:send`` (it is messaging, not record editing), so field techs and sales
can reach customers without being able to edit the CRM. The gating dependency
also resolves workspace membership, replacing the old ``get_workspace`` check;
``workspace_id`` (the path param) is the workspace identifier used throughout.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.api.deps import DB, CanReadCRM, CanSendComms, CanWriteCRM, CurrentUser
from app.api.service_errors import ServiceErrorRoute
from app.models.contact import Contact
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
    ContactCreate,
    ContactEngagementSummary,
    ContactIdsResponse,
    ContactListResponse,
    ContactResponse,
    ContactStatsResponse,
    ContactUpdate,
    CSVPreviewResponse,
    ImportResult,
    MessageResponse,
    QualificationSignals,
    QualifyContactResponse,
    SendMessageToContactRequest,
    TimelineItem,
)
from app.schemas.lead_source import AssignLeadSourceRequest, LeadAttributionFields
from app.services.contacts import (
    ContactAIStateService,
    ContactBulkService,
    ContactImportService,
    ContactQueryService,
    ContactService,
    ContactTimelineService,
)
from app.services.contacts.engagement_summary import get_engagement_summary
from app.services.contacts.exceptions import (
    ContactNotFoundError,
)
from app.services.dashboard.dashboard_service import invalidate_dashboard_cache
from app.services.exceptions import NotFoundError, ServiceUnavailableError, ValidationError
from app.services.lead_sources.attribution_service import (
    AttributionCleanupError,
    AttributionCleanupService,
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


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    workspace_id: uuid.UUID,
    contact_in: ContactCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> Contact:
    """Create a new contact."""
    service = ContactService(db)
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
    opportunities so the correction flows through to closed-won ROI.
    """
    service = AttributionCleanupService(db)
    try:
        await service.assign(
            workspace_id=workspace_id,
            contact_id=contact_id,
            lead_source_id=assign_in.lead_source_id,
            lead_source_campaign_id=assign_in.lead_source_campaign_id,
            source_type=assign_in.source_type,
        )
    except AttributionCleanupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    # Backfilled opportunities change closed-won attribution — refresh ROI now.
    await invalidate_dashboard_cache(workspace_id)


@router.get("/{contact_id}/timeline", response_model=list[TimelineItem])
async def get_contact_timeline(
    workspace_id: uuid.UUID,
    contact_id: int,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    limit: int = Query(100, ge=1, le=500),
) -> list[TimelineItem]:
    """Get the conversation timeline for a contact.

    Returns a unified timeline of SMS messages, calls, appointments, etc.
    """
    service = ContactTimelineService(db)
    timeline_items_data = await service.get_contact_timeline(
        contact_id=contact_id,
        workspace_id=workspace_id,
        limit=limit,
    )

    # Convert dicts to TimelineItem models
    return [TimelineItem(**item) for item in timeline_items_data]


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
