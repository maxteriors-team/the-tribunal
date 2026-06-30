"""Voice call management endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, CanReadCRM, CanSendComms, CurrentUser
from app.core.config import settings
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.phone_number import PhoneNumber
from app.schemas.call import (
    CallCreate,
    CallResponse,
    CapturedMessageResponse,
    LiveCallResponse,
    LiveCallsResponse,
    PaginatedCalls,
)
from app.services.calls.live_call_registry import get_live_call_registry
from app.services.telephony.telnyx_voice import TelnyxVoiceService

router = APIRouter()


@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def initiate_call(
    workspace_id: uuid.UUID,
    call_data: CallCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
) -> CallResponse:
    """Initiate outbound voice call.

    Args:
        workspace_id: Workspace ID
        call_data: Call request data
        current_user: Current user
        db: Database session

    Returns:
        Created Message record for the call
    """
    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telnyx not configured",
        )

    # Note: telnyx_connection_id is optional - the service auto-discovers
    # a Call Control Application ID if not provided

    # Verify the from_phone_number belongs to workspace
    result = await db.execute(
        apply_workspace_scope(select(PhoneNumber), PhoneNumber, workspace_id).where(
            PhoneNumber.phone_number == call_data.from_phone_number,
            PhoneNumber.voice_enabled.is_(True),
        )
    )
    phone_record = result.scalar_one_or_none()

    if not phone_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number not found or voice not enabled",
        )

    # Initiate call via Telnyx
    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        # Build webhook URL for call events
        api_base = settings.api_base_url or "https://example.com"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"

        # Connection ID is optional - service auto-discovers if not provided
        connection_id = settings.telnyx_connection_id if settings.telnyx_connection_id else None

        message = await voice_service.initiate_call(
            to_number=call_data.to_number,
            from_number=call_data.from_phone_number,
            connection_id=connection_id,
            webhook_url=webhook_url,
            db=db,
            workspace_id=workspace_id,
            contact_phone=call_data.contact_phone,
            agent_id=call_data.agent_id,
        )

        return CallResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            direction=message.direction,
            channel=message.channel,
            status=message.status,
            duration_seconds=message.duration_seconds,
            recording_url=message.recording_url,
            transcript=message.transcript,
            created_at=message.created_at,
            from_number=call_data.from_phone_number,
            to_number=call_data.to_number,
            agent_id=message.agent_id,
            is_ai=message.is_ai,
        )
    finally:
        await voice_service.close()


def _build_captured_messages(message: Message) -> list[CapturedMessageResponse]:
    """Map a call's loaded phone_messages relationship to response models."""
    captures = getattr(message, "phone_messages", None) or []
    return [
        CapturedMessageResponse(
            id=pm.id,
            caller_name=pm.caller_name,
            callback_number=pm.callback_number,
            reason=pm.reason,
            urgency=str(pm.urgency),
            preferred_callback_time=pm.preferred_callback_time,
            message_body=pm.message_body,
            status=str(pm.status),
            created_at=pm.created_at,
        )
        for pm in sorted(captures, key=lambda pm: pm.created_at)
    ]


def _build_call_response(
    message: Message,
    conversation: Conversation,
    agent_name: str | None = None,
    contact_name: str | None = None,
    contact_id: int | None = None,
    contact_avatar_url: str | None = None,
) -> CallResponse:
    """Build CallResponse with phone numbers from conversation."""
    # Determine from/to based on direction
    if message.direction == "outbound":
        from_number = conversation.workspace_phone
        to_number = conversation.contact_phone
    else:
        from_number = conversation.contact_phone
        to_number = conversation.workspace_phone

    return CallResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        direction=message.direction,
        channel=message.channel,
        status=message.status,
        duration_seconds=message.duration_seconds,
        recording_url=message.recording_url,
        transcript=message.transcript,
        created_at=message.created_at,
        from_number=from_number,
        to_number=to_number,
        contact_name=contact_name,
        contact_id=contact_id,
        contact_avatar_url=contact_avatar_url,
        agent_id=message.agent_id,
        agent_name=agent_name,
        is_ai=message.is_ai,
        booking_outcome=message.booking_outcome,
        captured_messages=_build_captured_messages(message),
    )


@router.get("", response_model=PaginatedCalls)
async def list_calls(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    direction: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
) -> PaginatedCalls:
    """List call history in workspace.

    Args:
        workspace_id: Workspace ID
        current_user: Current user
        db: Database session
        page: Page number
        page_size: Items per page
        direction: Filter by direction (inbound/outbound)
        status: Filter by status (completed/no_answer/busy/failed)
        search: Search by contact name

    Returns:
        Paginated list of calls
    """
    from sqlalchemy.orm import joinedload, selectinload

    # Query voice messages with their conversations, agents, and contacts
    query = (
        select(Message)
        .options(
            joinedload(Message.conversation).joinedload(Conversation.contact),
            joinedload(Message.agent),
            selectinload(Message.phone_messages),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.channel == "voice")
    )
    query = apply_workspace_scope(query, Conversation, workspace_id)

    # Apply direction filter
    if direction:
        query = query.where(Message.direction == direction)

    # Apply status filter
    if status:
        query = query.where(Message.status == status)

    # Apply contact name search
    if search:
        query = query.outerjoin(Contact, Conversation.contact_id == Contact.id).where(
            (Contact.first_name.ilike(f"%{search}%")) | (Contact.last_name.ilike(f"%{search}%"))
        )

    query = query.order_by(Message.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size, unique=True)

    # Aggregate stats query (same base filters, no pagination)
    stats_query = (
        select(
            func.count(Message.id).filter(Message.status == "completed"),
            func.coalesce(func.sum(Message.duration_seconds), 0),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.channel == "voice")
    )
    stats_query = apply_workspace_scope(stats_query, Conversation, workspace_id)
    if direction:
        stats_query = stats_query.where(Message.direction == direction)
    if status:
        stats_query = stats_query.where(Message.status == status)
    if search:
        stats_query = stats_query.outerjoin(Contact, Conversation.contact_id == Contact.id).where(
            (Contact.first_name.ilike(f"%{search}%")) | (Contact.last_name.ilike(f"%{search}%"))
        )
    stats_result = await db.execute(stats_query)
    completed_count, total_duration = stats_result.one()

    return PaginatedCalls(
        items=[
            _build_call_response(
                m,
                m.conversation,
                agent_name=m.agent.name if m.agent else None,
                contact_name=(m.conversation.contact.full_name if m.conversation.contact else None),
                contact_id=m.conversation.contact_id,
                contact_avatar_url=(
                    m.conversation.contact.avatar_url if m.conversation.contact else None
                ),
            )
            for m in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
        completed_count=completed_count,
        total_duration_seconds=int(total_duration),
    )


@router.get("/live", response_model=LiveCallsResponse)
async def list_live_calls(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> LiveCallsResponse:
    """List calls currently in progress in this workspace (supervision roster).

    Backed by the in-process live-call registry, so it reflects calls served by
    this backend instance. Used by the operator live-call panel to expose
    monitor / whisper / barge controls.
    """
    snapshots = get_live_call_registry().list_for_workspace(workspace_id)
    return LiveCallsResponse(
        items=[LiveCallResponse(**snapshot.as_dict()) for snapshot in snapshots]
    )


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    workspace_id: uuid.UUID,
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> CallResponse:
    """Get call details with recording and transcript.

    Args:
        workspace_id: Workspace ID
        call_id: Call (Message) ID
        current_user: Current user
        db: Database session

    Returns:
        Message record with call details
    """
    from sqlalchemy.orm import joinedload, selectinload

    # Get the message with conversation, agent, and contact
    result = await db.execute(
        select(Message)
        .options(
            joinedload(Message.conversation).joinedload(Conversation.contact),
            joinedload(Message.agent),
            selectinload(Message.phone_messages),
        )
        .where(
            Message.id == call_id,
            Message.channel == "voice",
        )
    )
    message = result.unique().scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    # Verify workspace access
    if message.conversation.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    return _build_call_response(
        message,
        message.conversation,
        agent_name=message.agent.name if message.agent else None,
        contact_name=(
            message.conversation.contact.full_name if message.conversation.contact else None
        ),
        contact_id=message.conversation.contact_id,
        contact_avatar_url=(
            message.conversation.contact.avatar_url if message.conversation.contact else None
        ),
    )


@router.post("/{call_id}/hangup")
async def hangup_call(
    workspace_id: uuid.UUID,
    call_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
) -> dict[str, bool]:
    """Hang up active call.

    Args:
        workspace_id: Workspace ID
        call_id: Call (Message) ID
        current_user: Current user
        db: Database session

    Returns:
        Success status
    """
    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telnyx not configured",
        )

    # Get the message
    result = await db.execute(
        select(Message).where(
            Message.id == call_id,
            Message.channel == "voice",
        )
    )
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    # Verify workspace access
    from app.models.conversation import Conversation

    conv_result = await db.execute(
        apply_workspace_scope(select(Conversation), Conversation, workspace_id).where(
            Conversation.id == message.conversation_id
        )
    )

    if not conv_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Hangup via Telnyx
    if not message.provider_message_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Call does not have a provider message ID",
        )

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        success = await voice_service.hangup_call(message.provider_message_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to hangup call",
            )

        return {"success": True}
    finally:
        await voice_service.close()
