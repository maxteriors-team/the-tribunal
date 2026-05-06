"""Telnyx webhook endpoints for SMS and voice events.

This module is a thin dispatch layer: it verifies webhooks, parses payloads,
and routes events to handlers in ``telnyx_message_handlers`` (SMS/MMS) and
``telnyx_call_handlers`` (voice).
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.api.webhooks.telnyx_call_handlers import (
    handle_call_answered,
    handle_call_hangup,
    handle_call_initiated,
    handle_machine_detection,
)
from app.api.webhooks.telnyx_message_handlers import (
    handle_delivery_status,
    handle_inbound_message,
)
from app.api.webhooks.telnyx_parser import verify_and_parse

router = APIRouter()
logger = structlog.get_logger()


EventHandler = Callable[[dict[str, Any], Any], Awaitable[None]]


_SMS_HANDLERS: dict[str, EventHandler] = {
    "message.received": handle_inbound_message,
    "message.sent": handle_delivery_status,
    "message.finalized": handle_delivery_status,
}


_VOICE_HANDLERS: dict[str, EventHandler] = {
    "call.initiated": handle_call_initiated,
    "call.answered": handle_call_answered,
    "call.hangup": handle_call_hangup,
    "call.machine.detection.ended": handle_machine_detection,
}


@router.post("/sms")
async def telnyx_sms_webhook(request: Request) -> dict[str, str]:
    """Handle incoming Telnyx SMS webhooks.

    Telnyx sends webhooks for:
    - message.received: Inbound SMS received
    - message.sent: Outbound message sent
    - message.finalized: Final delivery status
    """
    log = logger.bind(endpoint="telnyx_sms_webhook")

    parsed = await verify_and_parse(request, log)
    if parsed is None:
        return {"status": "error", "message": "Invalid JSON"}

    event_type, event_payload = parsed
    log = log.bind(event_type=event_type)
    log.info("webhook_received")

    handler = _SMS_HANDLERS.get(event_type)
    if handler is not None:
        try:
            await handler(event_payload, log)
        except Exception as exc:
            # Re-raise as 500 so Telnyx retries the webhook. Handlers are
            # idempotent on provider_message_id (see TelnyxSMSService
            # .process_inbound_message and .update_message_status), so a
            # retry will not double-process. Returning 200 here would mask
            # mid-write failures and leave permanent partial-write state.
            log.exception(
                "telnyx_sms_handler_failed",
                event_type=event_type,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise HTTPException(
                status_code=500,
                detail=f"Handler failed for {event_type}",
            ) from exc
    else:
        log.debug("unhandled_event_type")

    return {"status": "ok"}


@router.post("/voice")
async def telnyx_voice_webhook(request: Request) -> dict[str, str]:
    """Handle incoming Telnyx voice webhooks.

    Telnyx sends webhooks for:
    - call.initiated: Incoming call received
    - call.answered: Call was answered
    - call.hangup: Call ended
    - call.machine.detection.ended: Voicemail/human detection result
    """
    log = logger.bind(endpoint="telnyx_voice_webhook")

    parsed = await verify_and_parse(request, log)
    if parsed is None:
        return {"status": "error", "message": "Invalid JSON"}

    event_type, event_payload = parsed
    log = log.bind(event_type=event_type)
    log.info(
        "========== TELNYX VOICE WEBHOOK ==========",
        event_type=event_type,
        call_control_id=event_payload.get("call_control_id"),
        call_state=event_payload.get("state"),
        direction=event_payload.get("direction"),
    )

    handler = _VOICE_HANDLERS.get(event_type)
    if handler is not None:
        try:
            await handler(event_payload, log)
        except Exception as exc:
            # Re-raise as 500 so Telnyx retries the webhook. Voice handlers
            # are idempotent on call_control_id: handle_call_initiated
            # short-circuits if a Message already exists, handle_call_hangup
            # checks _TERMINAL_HANGUP_STATUSES before running side effects,
            # and handle_call_answered/handle_machine_detection look up the
            # Message row by provider_message_id. Returning 200 here would
            # mask mid-write failures and leave permanent partial state.
            log.exception(
                "telnyx_voice_handler_failed",
                event_type=event_type,
                call_control_id=event_payload.get("call_control_id"),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise HTTPException(
                status_code=500,
                detail=f"Handler failed for {event_type}",
            ) from exc
    else:
        log.info("unhandled_voice_event_type", event_type=event_type)

    return {"status": "ok"}
