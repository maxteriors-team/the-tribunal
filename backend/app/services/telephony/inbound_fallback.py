"""Fail-closed transfer and terminal-notice behavior for inbound calls."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.metrics import observe_inbound_fallback
from app.db.session import system_session
from app.models.conversation import Conversation, Message
from app.models.phone_number import PhoneNumber
from app.services.telephony.inbound_call_policy import (
    BUSY_NOTICE_TEXT,
    UNAVAILABLE_NOTICE_TEXT,
    InboundTerminalNotice,
    encode_inbound_terminal_state,
)
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.utils.phone import normalize_phone_safe


async def transfer_inbound_to_fallback(
    *,
    call_control_id: str,
    fallback_number: str | None,
    log: Any,
    reason: str,
) -> bool:
    """Answer and cold-transfer an inbound call without logging its destination."""
    observe_inbound_fallback("attempted")
    if not settings.telnyx_api_key:
        log.error("inbound_fallback_provider_unavailable", reason=reason)
        observe_inbound_fallback("unavailable")
        return False
    if not fallback_number or normalize_phone_safe(fallback_number) != fallback_number:
        log.error("inbound_fallback_not_configured", reason=reason)
        observe_inbound_fallback("unavailable")
        return False

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        await voice_service.answer_call(call_control_id)
        transferred = await voice_service.transfer_call(
            call_control_id=call_control_id,
            to_number=fallback_number,
            command_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"inbound-fallback:{call_control_id}",
                )
            ),
        )
        if transferred:
            log.warning("inbound_fallback_transfer_requested", reason=reason)
            observe_inbound_fallback("transferred")
        else:
            log.error("inbound_fallback_transfer_failed", reason=reason)
            observe_inbound_fallback("failed")
        return transferred
    finally:
        try:
            await voice_service.close()
        except Exception as exc:
            log.error(
                "inbound_fallback_provider_close_failed",
                error_type=type(exc).__name__,
            )


async def route_inbound_to_fallback(
    *,
    call_control_id: str,
    fallback_number: str | None,
    log: Any,
    reason: str,
) -> bool:
    """Try emergency transfer; otherwise play a bounded notice and end the call."""
    try:
        transferred = await transfer_inbound_to_fallback(
            call_control_id=call_control_id,
            fallback_number=fallback_number,
            log=log,
            reason=reason,
        )
    except Exception as exc:
        log.error(
            "inbound_fallback_transfer_error",
            reason=reason,
            error_type=type(exc).__name__,
        )
        observe_inbound_fallback("failed")
        transferred = False
    if not transferred:
        await end_inbound_call_with_notice(
            call_control_id=call_control_id,
            notice="unavailable",
            log=log,
            reason=reason,
        )
    return transferred


async def route_inbound_to_configured_fallback(
    *,
    call_control_id: str,
    log: Any,
    reason: str,
) -> bool:
    """Resolve fallback only through the call's workspace-scoped persisted state."""
    fallback_number: str | None = None
    try:
        async with system_session("resolve signed inbound call fallback") as db:
            result = await db.execute(
                select(PhoneNumber.inbound_fallback_number)
                .join(Conversation, Conversation.workspace_id == PhoneNumber.workspace_id)
                .join(Message, Message.conversation_id == Conversation.id)
                .where(
                    Message.provider_message_id == call_control_id,
                    Message.direction == "inbound",
                    PhoneNumber.phone_number == Conversation.workspace_phone,
                )
            )
            fallback_number = result.scalar_one_or_none()
    except Exception as exc:
        log.error(
            "inbound_fallback_lookup_failed",
            reason=reason,
            error_type=type(exc).__name__,
        )

    return await route_inbound_to_fallback(
        call_control_id=call_control_id,
        fallback_number=fallback_number,
        log=log,
        reason=reason,
    )


async def end_inbound_call_with_notice(
    *,
    call_control_id: str,
    notice: InboundTerminalNotice,
    log: Any,
    reason: str,
) -> None:
    """Speak one non-sensitive terminal notice, then hang up on its ended webhook."""
    if not settings.telnyx_api_key:
        log.error("inbound_terminal_notice_provider_unavailable", reason=reason)
        return

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        await voice_service.answer_call(call_control_id)
        spoken = await voice_service.speak_text(
            call_control_id=call_control_id,
            text=BUSY_NOTICE_TEXT if notice == "busy" else UNAVAILABLE_NOTICE_TEXT,
            client_state=encode_inbound_terminal_state(notice),
            command_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"inbound-terminal:{call_control_id}:{notice}",
                )
            ),
        )
        if spoken:
            log.warning("inbound_terminal_notice_started", notice=notice, reason=reason)
            return
        log.error("inbound_terminal_notice_failed", notice=notice, reason=reason)
        await voice_service.hangup_call(call_control_id)
    except Exception as exc:
        log.error(
            "inbound_terminal_notice_error",
            notice=notice,
            reason=reason,
            error_type=type(exc).__name__,
        )
        try:
            await voice_service.hangup_call(call_control_id)
        except Exception as hangup_exc:
            log.error(
                "inbound_terminal_hangup_failed",
                notice=notice,
                reason=reason,
                error_type=type(hangup_exc).__name__,
            )
    finally:
        try:
            await voice_service.close()
        except Exception as exc:
            log.error(
                "inbound_terminal_provider_close_failed",
                error_type=type(exc).__name__,
            )
