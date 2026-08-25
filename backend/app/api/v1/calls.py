"""Voice call management endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CanReadCRM, CanSendComms, CurrentUser, WorkspaceAccess
from app.core.config import settings
from app.core.encryption import hash_phone
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.agent import Agent
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
    WebRTCTokenResponse,
)
from app.services.calls.live_call_registry import get_live_call_registry
from app.services.rate_limiting.softphone_limiter import (
    SoftphoneRateLimitError,
    SoftphoneRateLimitUnavailableError,
    enforce_softphone_call_limits,
    enforce_softphone_token_limit,
)
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.services.telephony.telnyx_webrtc import TelnyxWebRTCError, TelnyxWebRTCService
from app.services.telephony.user_call import (
    RepNumberNotAllowedError,
    VoiceProviderUnavailableError,
    resolve_rep_callback_number,
    start_user_call,
)

router = APIRouter()


async def _resolve_voice_agent_id(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    requested_agent_id: uuid.UUID | None,
    phone_record: PhoneNumber,
    workspace_phone: str,
    contact_phone: str,
) -> uuid.UUID | None:
    """Resolve which voice agent should handle an ``mode="ai"`` outbound call.

    Precedence: the explicitly requested agent, then the agent already assigned
    to this contact's conversation, then the agent assigned to the outbound
    number, then any active voice-capable agent in the workspace.

    Returns None when the workspace has no usable voice agent. The caller must
    reject the request in that case: dialing a contact with no agent and no
    human leg answers into silence.
    """
    voice_capable = (
        Agent.workspace_id == workspace_id,
        Agent.is_active.is_(True),
        Agent.channel_mode.in_(("voice", "both")),
    )

    if requested_agent_id is not None:
        # Scope the lookup to the workspace so an agent id from another tenant
        # can never be attached to this workspace's call.
        result = await db.execute(
            select(Agent.id).where(Agent.id == requested_agent_id, *voice_capable)
        )
        return result.scalar_one_or_none()

    conv_result = await db.execute(
        select(Conversation.assigned_agent_id).where(
            Conversation.workspace_id == workspace_id,
            Conversation.workspace_phone_hash == hash_phone(workspace_phone),
            Conversation.contact_phone_hash == hash_phone(contact_phone),
            Conversation.assigned_agent_id.is_not(None),
        )
    )
    for candidate in (conv_result.scalars().first(), phone_record.assigned_agent_id):
        if candidate is None:
            continue
        agent_result = await db.execute(
            select(Agent.id).where(Agent.id == candidate, *voice_capable)
        )
        resolved = agent_result.scalar_one_or_none()
        if resolved is not None:
            return resolved

    fallback = await db.execute(
        select(Agent.id).where(*voice_capable).order_by(Agent.created_at.asc()).limit(1)
    )
    return fallback.scalars().first()


@router.post("/webrtc/token", response_model=WebRTCTokenResponse)
async def issue_webrtc_token(
    workspace_id: uuid.UUID,
    response: Response,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
    workspace: WorkspaceAccess,
) -> WebRTCTokenResponse:
    """Mint a memory-only Telnyx JWT for the authenticated operator's browser."""
    del membership, workspace
    if not settings.telnyx_api_key or not settings.telnyx_webrtc_connection_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser calling is not configured",
        )

    try:
        await enforce_softphone_token_limit(user_id=current_user.id)
    except SoftphoneRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "3600"},
        ) from exc
    except SoftphoneRateLimitUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    service: TelnyxWebRTCService | None = None
    try:
        service = TelnyxWebRTCService(
            settings.telnyx_api_key,
            settings.telnyx_webrtc_connection_id,
        )
        token = await service.issue_user_token(db, current_user)
    except TelnyxWebRTCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    finally:
        if service is not None:
            await service.close()

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return WebRTCTokenResponse(token=token)


async def _enforce_paid_call_limits(workspace_id: uuid.UUID, user_id: int) -> None:
    """Apply one atomic spend guard before any client-selected call mode."""
    try:
        await enforce_softphone_call_limits(workspace_id=str(workspace_id), user_id=user_id)
    except SoftphoneRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": "3600"},
        ) from exc
    except SoftphoneRateLimitUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


async def _start_browser_operator_call(
    *,
    db: AsyncSession,
    voice_service: TelnyxVoiceService,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    call_data: CallCreate,
    connection_id: str | None,
    webhook_url: str,
) -> Message:
    """Authorize and dial one server-owned browser identity."""
    if not settings.telnyx_webrtc_connection_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser calling is not configured",
        )
    browser_service: TelnyxWebRTCService | None = None
    try:
        browser_service = TelnyxWebRTCService(
            settings.telnyx_api_key, settings.telnyx_webrtc_connection_id
        )
        credential = await browser_service.ensure_user_credential(db, current_user)
    except TelnyxWebRTCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    finally:
        if browser_service is not None:
            await browser_service.close()

    try:
        return await start_user_call(
            db=db,
            voice_service=voice_service,
            workspace_id=workspace_id,
            user_id=current_user.id,
            to_number=call_data.to_number,
            from_number=call_data.from_phone_number,
            sip_username=credential.sip_username,
            contact_phone=call_data.contact_phone,
            connection_id=connection_id,
            webhook_url=webhook_url,
        )
    except VoiceProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def initiate_call(
    workspace_id: uuid.UUID,
    call_data: CallCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
    workspace: WorkspaceAccess,
) -> CallResponse:
    """Initiate an outbound voice call handled by AI, phone callback, or browser.

    Human modes ring the operator before the contact, so nobody is dialed into
    silence. Browser mode uses a server-derived internal SIP target only.

    Args:
        workspace_id: Workspace ID
        call_data: Call request data
        current_user: Current user
        db: Database session
        membership: Caller's workspace membership (comms-send capability)
        workspace: Workspace the call is billed to

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

    await _enforce_paid_call_limits(workspace_id, current_user.id)

    # Initiate call via Telnyx
    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        # Build webhook URL for call events
        api_base = settings.api_base_url or "https://example.com"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"

        # Connection ID is optional - service auto-discovers if not provided
        connection_id = settings.telnyx_connection_id if settings.telnyx_connection_id else None

        if call_data.mode == "user":
            try:
                rep_number = await resolve_rep_callback_number(
                    db=db,
                    user=current_user,
                    workspace=workspace,
                    requested=call_data.user_phone_number,
                )
            except RepNumberNotAllowedError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc

            try:
                message = await start_user_call(
                    db=db,
                    voice_service=voice_service,
                    workspace_id=workspace_id,
                    user_id=current_user.id,
                    to_number=call_data.to_number,
                    from_number=call_data.from_phone_number,
                    rep_number=rep_number,
                    contact_phone=call_data.contact_phone,
                    connection_id=connection_id,
                    webhook_url=webhook_url,
                )
            except VoiceProviderUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=str(exc),
                ) from exc
        elif call_data.mode == "browser":
            message = await _start_browser_operator_call(
                db=db,
                voice_service=voice_service,
                workspace_id=workspace_id,
                current_user=current_user,
                call_data=call_data,
                connection_id=connection_id,
                webhook_url=webhook_url,
            )
        else:
            # An AI call with no agent starts no audio stream, so the contact
            # answers to dead air. Refuse the call instead of burning the lead.
            agent_id = await _resolve_voice_agent_id(
                db=db,
                workspace_id=workspace_id,
                requested_agent_id=call_data.agent_id,
                phone_record=phone_record,
                workspace_phone=voice_service.normalize_e164(call_data.from_phone_number),
                contact_phone=voice_service.normalize_e164(
                    call_data.contact_phone or call_data.to_number
                ),
            )
            if agent_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "No active voice agent available for this call. Select an agent, "
                        "or use a human mode to take the call yourself."
                    ),
                )

            message = await voice_service.initiate_call(
                to_number=call_data.to_number,
                from_number=call_data.from_phone_number,
                connection_id=connection_id,
                webhook_url=webhook_url,
                db=db,
                workspace_id=workspace_id,
                contact_phone=call_data.contact_phone,
                agent_id=agent_id,
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
