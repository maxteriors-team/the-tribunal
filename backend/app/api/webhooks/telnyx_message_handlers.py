"""Telnyx SMS/MMS webhook handlers."""

from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.metrics import observe_sms_bounce
from app.db.session import AsyncSessionLocal
from app.models.conversation import Message, MessageChannel
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.ai.text_agent import schedule_ai_response
from app.services.approval.command_processor_service import command_processor_service
from app.services.campaigns.conversation_syncer import CampaignConversationSyncer
from app.services.push_notifications import push_notification_service
from app.services.telephony.inbound_text import InboundTextEvent, process_inbound_text_event
from app.services.telephony.telnyx import TelnyxSMSService

_conversation_syncer = CampaignConversationSyncer()


async def handle_inbound_message(payload: dict[str, Any], log: Any) -> None:  # noqa: PLR0912, PLR0915
    """Handle inbound SMS message."""
    from app.utils.phone import normalize_phone_safe

    # Extract message details
    from_number = payload.get("from", {}).get("phone_number", "")
    to_list = payload.get("to", [])
    to_number = to_list[0].get("phone_number", "") if to_list else ""
    body = payload.get("text", "")
    message_id = payload.get("id", "")

    # Normalize phone numbers to E.164 format for consistent lookups
    from_number = normalize_phone_safe(from_number) or from_number
    to_number = normalize_phone_safe(to_number) or to_number

    log = log.bind(from_number=from_number, to_number=to_number, message_id=message_id)
    log.info("processing_inbound_sms")

    if not all([from_number, to_number, body]):
        log.warning("missing_required_fields")
        return

    async with AsyncSessionLocal() as db:
        # Look up workspace by phone number
        result = await db.execute(select(PhoneNumber).where(PhoneNumber.phone_number == to_number))
        phone_record = result.scalar_one_or_none()

        if not phone_record:
            log.warning("phone_number_not_found", to_number=to_number)
            return

        workspace_id = phone_record.workspace_id

        telnyx_api_key = settings.telnyx_api_key
        if not telnyx_api_key:
            log.error("no_telnyx_api_key")
            return

        sms_service = TelnyxSMSService(telnyx_api_key)
        try:
            event = InboundTextEvent(
                provider_message_id=message_id,
                from_number=from_number,
                to_number=to_number,
                body=body,
                workspace_id=workspace_id,
                channel=MessageChannel.SMS,
            )

            async def ingest_message(db: Any, inbound_event: InboundTextEvent) -> Message:
                return await sms_service.process_inbound_message(
                    db=db,
                    provider_message_id=inbound_event.provider_message_id,
                    from_number=inbound_event.from_number,
                    to_number=inbound_event.to_number,
                    body=inbound_event.body,
                    workspace_id=inbound_event.workspace_id,
                )

            message = await process_inbound_text_event(
                db=db,
                event=event,
                ingest_message=ingest_message,
                log=log,
                command_processor=command_processor_service,
                conversation_syncer=_conversation_syncer,
                schedule_ai_response_fn=schedule_ai_response,
                push_service=push_notification_service,
                check_operator_fn=_check_operator,
            )
            if message is not None:
                log.info("inbound_sms_processed", message_id=str(message.id))
        finally:
            await sms_service.close()


async def handle_delivery_status(payload: dict[str, Any], log: Any) -> None:  # noqa: PLR0915
    """Handle delivery status update with bounce classification."""
    message_id = payload.get("id", "")
    to_info = payload.get("to", [{}])[0] if payload.get("to") else {}
    status = to_info.get("status", "unknown")

    # Extract error details for bounce classification
    errors = payload.get("errors", [])
    first_error = errors[0] if errors else {}
    error_code = first_error.get("code") if first_error else None
    error_message = first_error.get("detail") if first_error else None

    log = log.bind(message_id=message_id, status=status, error_code=error_code)
    log.info("processing_delivery_status")

    async with AsyncSessionLocal() as db:
        telnyx_api_key = settings.telnyx_api_key
        if not telnyx_api_key:
            log.error("no_telnyx_api_key")
            return

        sms_service = TelnyxSMSService(telnyx_api_key)
        try:
            # Update message status with bounce classification. We capture the
            # message's previous status so downstream campaign-stats updates
            # can dedup duplicate / redelivered Telnyx webhooks instead of
            # double-counting delivered/failed messages.
            message, previous_message_status = await sms_service.update_message_status(
                db=db,
                provider_message_id=message_id,
                status=status,
                error_code=error_code,
                error_message=error_message,
            )

            # Track delivery stats if we have a phone number ID
            if message and message.from_phone_number_id:
                from app.services.rate_limiting.bounce_classifier import BounceClassifier
                from app.services.rate_limiting.reputation_tracker import ReputationTracker

                tracker = ReputationTracker()

                if message.status == "delivered":
                    await tracker.increment_delivered(message.from_phone_number_id, db)
                    log.info("delivery_tracked", phone_number_id=str(message.from_phone_number_id))

                elif message.status == "failed" and error_code:
                    # Classify the bounce
                    bounce_type, bounce_category = BounceClassifier.classify_error(
                        error_code, error_message
                    )

                    # Update message with bounce classification
                    message.bounce_type = bounce_type
                    message.bounce_category = bounce_category
                    message.carrier_error_code = error_code
                    await db.commit()

                    # Track appropriate counter
                    if bounce_type == "hard":
                        await tracker.increment_hard_bounce(message.from_phone_number_id, db)
                    elif bounce_type == "soft":
                        await tracker.increment_soft_bounce(message.from_phone_number_id, db)
                    elif bounce_type == "spam_complaint":
                        await tracker.increment_spam_complaint(message.from_phone_number_id, db)

                    # Emit Prometheus counter (workspace_id resolved via the
                    # phone_number record, which is the canonical owner of
                    # the from_phone_number_id we already loaded above).
                    if bounce_type:
                        from app.models.phone_number import PhoneNumber as _PhoneNumber

                        ws_id = None
                        phone_row = await db.get(_PhoneNumber, message.from_phone_number_id)
                        if phone_row is not None:
                            ws_id = phone_row.workspace_id
                        observe_sms_bounce(ws_id, bounce_type=bounce_type)

                    log.info(
                        "bounce_tracked",
                        phone_number_id=str(message.from_phone_number_id),
                        bounce_type=bounce_type,
                        bounce_category=bounce_category,
                    )

            # Update campaign delivery stats (only for final statuses)
            if message and message.conversation_id and message.status in ("delivered", "failed"):
                try:
                    from app.services.campaigns.campaign_sms_stats import (
                        update_campaign_sms_delivery,
                    )

                    await update_campaign_sms_delivery(
                        db=db,
                        conversation_id=message.conversation_id,
                        delivered=(message.status == "delivered"),
                        log=log,
                        previous_status=previous_message_status,
                    )
                except Exception as e:
                    log.exception("campaign_delivery_stats_failed", error=str(e))

        finally:
            await sms_service.close()


async def _check_operator(db: Any, from_number: str, workspace_id: Any) -> User | None:
    """Check if the sender is a workspace member texting from their registered phone."""
    from app.utils.phone import normalize_phone_e164

    try:
        normalized = normalize_phone_e164(from_number)
    except Exception:
        return None

    result = await db.execute(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            User.phone_number == normalized,
            WorkspaceMembership.workspace_id == workspace_id,
            User.is_active == True,  # noqa: E712
        )
    )
    user: User | None = result.scalar_one_or_none()
    return user
