"""Telnyx voice call webhook handlers."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.api.webhooks.telnyx_parser import extract_phone_numbers
from app.core.config import settings
from app.core.encryption import hash_phone
from app.core.metrics import (
    observe_inbound_call_summary,
    observe_inbound_disclosure,
    observe_voice_call_completed,
    observe_voice_call_started,
)
from app.db.session import AsyncSessionLocal
from app.models.phone_number import PhoneNumber
from app.services.lead_sources.attribution_service import apply_tracking_number_attribution
from app.services.push_notifications import push_notification_service
from app.services.rate_limiting.softphone_limiter import (
    InboundCallerRateLimitError,
    SoftphoneRateLimitError,
    SoftphoneRateLimitUnavailableError,
    enforce_inbound_call_limits,
    release_inbound_call_capacity,
    reserve_inbound_call_capacity,
)
from app.services.telephony.call_outcome_classifier import CallOutcomeClassifier
from app.services.telephony.inbound_call_policy import (
    DISCLOSURE_VERSION,
    decode_inbound_disclosure_state,
    decode_inbound_terminal_state,
    encode_inbound_disclosure_state,
)
from app.services.telephony.inbound_call_readiness import (
    evaluate_inbound_call_readiness,
)
from app.services.telephony.inbound_routing import classify_inbound_reason
from app.services.telephony.inbound_screening import InboundCallScreener
from app.services.telephony.voice_agent_resolver import VoiceAgentResolver

_call_classifier = CallOutcomeClassifier()
_voice_agent_resolver = VoiceAgentResolver()
_inbound_screener = InboundCallScreener()

# Terminal message statuses set by the hangup classifier. If a Message is
# already in one of these states when a hangup webhook arrives, it's a Telnyx
# retry of an event we've already processed and side effects (engagement
# scoring, campaign call counters) must NOT run again.
_TERMINAL_HANGUP_STATUSES = frozenset({"completed", "failed", "no_answer"})


async def _route_challenged_inbound_call(
    phone_record: PhoneNumber, call_control_id: str, log: Any
) -> None:
    """Keep legacy voicemail recording outside the no-recording AI pilot."""
    if phone_record.inbound_ai_enabled:
        await _transfer_inbound_to_fallback(
            call_control_id,
            phone_record.inbound_fallback_number,
            log,
            reason="screening_challenge",
        )
    else:
        await take_inbound_voicemail(call_control_id, log)


async def handle_call_initiated(payload: dict[Any, Any], log: Any) -> None:  # noqa: PLR0915
    """Handle incoming call."""
    call_control_id = payload.get("call_control_id", "")
    call_state = payload.get("state", "")
    from_number, to_number = extract_phone_numbers(payload)

    log = log.bind(call_control_id=call_control_id, call_state=call_state)
    log.info("processing_call_initiated")

    if not all([call_control_id, from_number, to_number]):
        log.warning("missing_required_fields")
        return

    async with AsyncSessionLocal() as db:
        # Look up workspace by phone number
        result = await db.execute(select(PhoneNumber).where(PhoneNumber.phone_number == to_number))
        phone_record = result.scalar_one_or_none()

        if not phone_record:
            log.warning("phone_number_not_found_for_inbound_call")
            return

        workspace_id = phone_record.workspace_id

        # Create message record for incoming call
        from app.models.contact import Contact
        from app.models.conversation import Conversation, Message

        # Idempotency: Telnyx retries on 5xx/timeout, so we may receive the same
        # call.initiated event multiple times. Bail out early if we've already
        # created a Message for this call_control_id to avoid duplicate ringing
        # rows, duplicate push notifications, and double-firing auto-answer.
        existing_result = await db.execute(
            select(Message.id).where(Message.provider_message_id == call_control_id)
        )
        if existing_result.scalar_one_or_none() is not None:
            log.info(
                "call_initiated_duplicate_skipped",
                call_control_id=call_control_id,
            )
            return

        # Get or create conversation. The conversation phone columns are
        # Fernet-encrypted, so match on the deterministic lookup hashes.
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.workspace_phone_hash == hash_phone(to_number),
                Conversation.contact_phone_hash == hash_phone(from_number),
            )
        )
        conversation = conv_result.scalar_one_or_none()
        contact: Contact | None = None

        if not conversation:
            from app.utils.phone import phone_lookup_variants

            # Match the caller by deterministic phone hash, not the Fernet-
            # encrypted ``phone_number`` column: that column's ciphertext differs
            # every write, so an ``== from_number`` comparison never matches and
            # every known caller looked like a brand-new contact. Hash all E.164/
            # national variants so formatting differences still resolve.
            phone_hashes = [hash_phone(v) for v in phone_lookup_variants(from_number)]
            contact = None
            if phone_hashes:
                contact_result = await db.execute(
                    select(Contact)
                    .where(
                        Contact.workspace_id == workspace_id,
                        Contact.phone_hash.in_(phone_hashes),
                    )
                    .limit(1)
                )
                contact = contact_result.scalars().first()

            conversation = Conversation(
                workspace_id=workspace_id,
                contact_id=contact.id if contact else None,
                workspace_phone=to_number,
                contact_phone=from_number,
                channel="voice",
                ai_enabled=phone_record.inbound_ai_enabled,
            )
            db.add(conversation)
            await db.flush()
        elif conversation.contact_id is not None:
            contact = await db.get(Contact, conversation.contact_id)

        # Create inbound message
        message = Message(
            conversation_id=conversation.id,
            provider_message_id=call_control_id,
            direction="inbound",
            channel="voice",
            body="",
            status="ringing",
            voice_disclosure_status=("failed" if phone_record.inbound_ai_enabled else None),
            voice_disclosure_version=(
                DISCLOSURE_VERSION if phone_record.inbound_ai_enabled else None
            ),
        )
        db.add(message)

        # Update conversation
        conversation.channel = "voice"
        conversation.last_message_preview = "Incoming call"
        conversation.last_message_at = datetime.now(UTC)

        # Speed-to-lead SLA: anchor the lead's first inbound touch (the call).
        from app.services.sla import mark_inbound_lead

        mark_inbound_lead(conversation)

        if contact is not None and phone_record.lead_source_id is not None:
            await apply_tracking_number_attribution(db, contact, phone_record)
            log.info(
                "tracking_number_attribution_applied",
                contact_id=contact.id,
                lead_source_id=str(phone_record.lead_source_id),
            )

        await db.commit()
        await db.refresh(message)

        observe_voice_call_started(workspace_id)
        log.info("call_initiated_processed", message_id=str(message.id))

        # Inbound spam screening: check the caller against opt-out / blocklist
        # / reputation and apply the workspace spam policy. The outcome is
        # persisted on the call's Message row for audit and downstream UI.
        screening = await _inbound_screener.screen(db, workspace_id, from_number, log)
        message.screening_decision = screening.decision.value
        message.screening_reason = screening.reason

        # Reason-based routing: classify the caller's intent early (from a
        # returning caller's history) so the call can be routed to the right
        # department agent/queue when answered.
        routing_reason = await classify_inbound_reason(db, workspace_id, conversation, log)
        if routing_reason:
            message.routing_reason = routing_reason

        await db.commit()

        # Reject screened-out spam callers before answering. We hang up the
        # ringing leg; no agent is engaged and no push is sent.
        if screening.is_rejected:
            log.info(
                "inbound_call_rejected_spam",
                screening_reason=screening.reason,
                call_control_id=call_control_id,
            )
            await _reject_inbound_call(call_control_id, log)
            return

        # Push notification for incoming call
        try:
            await push_notification_service.send_to_workspace_members(
                db=db,
                workspace_id=str(workspace_id),
                title="Incoming Call",
                body=from_number,
                data={
                    "type": "call",
                    "messageId": str(message.id),
                    "screen": "/calls",
                },
                notification_type="call",
                channel_id="calls",
            )
        except Exception as e:
            log.error("push_notification_failed", error_type=type(e).__name__)

        # Legacy screening records voicemail. The no-recording AI pilot instead
        # sends challenged callers to its staffed emergency fallback.
        if screening.needs_challenge:
            log.info(
                "inbound_call_challenged",
                screening_reason=screening.reason,
                call_control_id=call_control_id,
            )
            await _route_challenged_inbound_call(phone_record, call_control_id, log)
            return

        # Auto-answer calls if phone number has an assigned active agent. The
        # classified routing reason picks a department-specific agent when the
        # workspace defines a route for it.
        await auto_answer_call_if_agent_assigned(
            call_control_id=call_control_id,
            phone_record=phone_record,
            conversation=conversation,
            log=log,
            reason=message.routing_reason,
            caller_phone=from_number,
        )


async def _speak_inbound_disclosure(
    db: Any,
    message: Any,
    call_control_id: str,
    log: Any,
) -> None:
    """Claim and speak the versioned notice before caller audio can stream."""
    from app.models.conversation import Message
    from app.models.workspace import Workspace
    from app.services.telephony.inbound_call_policy import build_inbound_disclosure
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    conversation = message.conversation
    if conversation is None or message.voice_disclosure_status not in {"pending", "speaking"}:
        return

    phone_result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.workspace_id == conversation.workspace_id,
            PhoneNumber.phone_number == conversation.workspace_phone,
        )
    )
    phone_record = phone_result.scalar_one_or_none()
    fallback_number = phone_record.inbound_fallback_number if phone_record else None
    readiness = None
    if phone_record is not None and phone_record.inbound_ai_enabled:
        readiness = await evaluate_inbound_call_readiness(
            db,
            workspace_id=conversation.workspace_id,
            phone_number=phone_record,
            assigned_agent_id=message.agent_id,
            fallback_number=fallback_number,
            transfer_destination_number=None,
        )

    if readiness is None or not readiness.ready or readiness.agent is None:
        await db.execute(
            update(Message)
            .where(
                Message.id == message.id,
                Message.voice_disclosure_status.in_(("pending", "speaking")),
            )
            .values(voice_disclosure_status="failed")
        )
        await db.commit()
        observe_inbound_disclosure(conversation.workspace_id, "failed")
        log.warning(
            "inbound_disclosure_prerequisite_failed",
            blocked_checks=(
                [check.code for check in readiness.checks if not check.ready]
                if readiness is not None
                else ["call_state"]
            ),
        )
        await _transfer_inbound_to_fallback(
            call_control_id,
            fallback_number,
            log,
            reason="disclosure_prerequisite_failed",
        )
        return

    business_name = await db.scalar(
        select(Workspace.name).where(Workspace.id == conversation.workspace_id)
    )
    claim = await db.execute(
        update(Message)
        .where(
            Message.id == message.id,
            Message.voice_disclosure_status == "pending",
        )
        .values(
            voice_disclosure_status="speaking",
            voice_disclosure_version=DISCLOSURE_VERSION,
        )
        .returning(Message.id)
    )
    claimed = claim.scalar_one_or_none() is not None
    await db.commit()
    if not claimed:
        current_status = await db.scalar(
            select(Message.voice_disclosure_status).where(Message.id == message.id)
        )
        if current_status != "speaking":
            return

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        spoken = await voice_service.speak_text(
            call_control_id=call_control_id,
            text=build_inbound_disclosure(business_name),
            client_state=encode_inbound_disclosure_state(message.id),
            command_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"inbound-disclosure:{message.id}",
                )
            ),
        )
    except Exception as exc:
        log.error(
            "inbound_disclosure_speak_error",
            error_type=type(exc).__name__,
        )
        spoken = False
    finally:
        await voice_service.close()

    if spoken:
        if claimed:
            observe_inbound_disclosure(conversation.workspace_id, "started")
        log.info(
            "inbound_disclosure_started",
            disclosure_version=DISCLOSURE_VERSION,
        )
        return

    await db.execute(
        update(Message)
        .where(
            Message.id == message.id,
            Message.voice_disclosure_status == "speaking",
        )
        .values(voice_disclosure_status="failed")
    )
    await db.commit()
    observe_inbound_disclosure(conversation.workspace_id, "failed")
    await _transfer_inbound_to_fallback(
        call_control_id,
        fallback_number,
        log,
        reason="disclosure_failed",
    )


async def handle_call_answered(payload: dict[Any, Any], log: Any) -> None:  # noqa: PLR0912, PLR0915
    """Handle call answered event."""
    from app.models.agent import Agent
    from app.models.conversation import Conversation, Message, MessageStatus
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    call_control_id = payload.get("call_control_id", "")
    call_state = payload.get("state", "")
    direction = payload.get("direction", "")

    log = log.bind(call_control_id=call_control_id, call_state=call_state, direction=direction)
    log.info("========== CALL ANSWERED ==========")

    # Warm-transfer closer leg: this answered leg is the human closer we dialed
    # for a warm handoff (not a normal AI call). Speak the briefing here; the
    # bridge into the caller leg happens on call.speak.ended. Short-circuit so
    # we don't start AI audio streaming on the closer leg.
    if await _handle_transfer_leg_answered(call_control_id, log):
        return

    # User-mode outbound call: one of the two legs we originated just answered.
    # The rep leg triggers the contact dial; the contact leg triggers the
    # bridge. Either way there is no AI to stream, so short-circuit.
    if await _handle_user_call_leg_answered(
        call_control_id,
        log,
        client_state=payload.get("client_state"),
    ):
        return

    async with AsyncSessionLocal() as db:
        # Get message with conversation loaded
        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_control_id)
        )
        message = result.scalar_one_or_none()

        if not message:
            log.error("message_not_found_for_call", call_control_id=call_control_id)
            return

        message.status = MessageStatus.ANSWERED

        # Speed-to-lead SLA: answering an inbound call is the first response.
        if message.direction == "inbound" and message.conversation is not None:
            from app.services.sla import record_first_response_and_maybe_alert

            await record_first_response_and_maybe_alert(
                db, message.conversation, datetime.now(UTC), log
            )

        await db.commit()

        if message.direction == "inbound":
            try:
                await _speak_inbound_disclosure(db, message, call_control_id, log)
            except Exception as exc:
                from app.services.telephony.inbound_fallback import (
                    route_inbound_to_configured_fallback,
                )

                log.error(
                    "inbound_disclosure_handler_failed",
                    error_type=type(exc).__name__,
                )
                await route_inbound_to_configured_fallback(
                    call_control_id=call_control_id,
                    log=log,
                    reason="disclosure_handler_failed",
                )
            return

        # Determine agent_id: prefer message.agent_id, fall back to conversation's assigned_agent_id
        agent_id = message.agent_id
        if not agent_id and message.conversation and message.conversation.assigned_agent_id:
            agent_id = message.conversation.assigned_agent_id

        # For outbound calls with an agent, start audio streaming
        if message.direction == "outbound" and agent_id:
            log.info("outbound_call_answered_starting_stream", agent_id=str(agent_id))

            # Get agent to check if it supports voice
            agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent = agent_result.scalar_one_or_none()

            if not agent or not agent.is_active:
                agent_str = str(agent_id) if agent_id else None
                log.info("agent_not_found_or_inactive", agent_id=agent_str)
                return

            # Assign agent to conversation if not already assigned
            if message.conversation and not message.conversation.assigned_agent_id:
                conv_result = await db.execute(
                    select(Conversation).where(Conversation.id == message.conversation_id)
                )
                conv = conv_result.scalar_one_or_none()
                if conv:
                    conv.assigned_agent_id = agent.id
                    conv.ai_enabled = True
                    await db.commit()
                    log.info("assigned_agent_to_conversation", agent_id=str(agent.id))

            # Start audio streaming
            if not settings.telnyx_api_key:
                log.error("no_telnyx_api_key_for_streaming")
                return

            voice_service = TelnyxVoiceService(settings.telnyx_api_key)
            try:
                api_base = settings.api_base_url or "https://example.com"
                streaming_started = await voice_service.start_audio_streaming(
                    call_control_id=call_control_id,
                    api_base_url=api_base,
                    is_outbound=True,
                )

                if streaming_started:
                    log.info("audio_streaming_started", call_control_id=call_control_id)
                else:
                    log.error("failed_to_start_audio_streaming", call_control_id=call_control_id)

                # Start recording if agent has it enabled
                if agent.enable_recording:
                    recorded = await voice_service.start_recording(call_control_id)
                    if recorded:
                        log.info("call_recording_started", call_control_id=call_control_id)
                    else:
                        log.warning("call_recording_failed", call_control_id=call_control_id)
            finally:
                await voice_service.close()


async def _reconcile_booking_outcome(
    db: Any,
    message: Any,
    log: Any,
) -> str | None:
    """Check for booking evidence when message.booking_outcome is NULL.

    Strategies:
    1. Query Appointment by message_id (direct link from VoiceToolExecutor).
    2. Query Appointment by contact_id + agent_id created within last 5 minutes.

    Returns the reconciled booking_outcome or None.
    """
    if message.booking_outcome:
        outcome: str = message.booking_outcome
        return outcome

    from datetime import timedelta

    from app.models.appointment import Appointment

    # Strategy 1: Direct message_id link
    appt_result = await db.execute(select(Appointment).where(Appointment.message_id == message.id))
    appt = appt_result.scalar_one_or_none()
    if appt:
        log.info("reconciled_booking_via_message_id", appointment_id=appt.id)
        return "success"

    # Strategy 2: Fuzzy match by contact + agent + recent creation
    if message.conversation and message.conversation.contact_id and message.agent_id:
        cutoff = datetime.now(UTC) - timedelta(minutes=5)
        fuzzy_result = await db.execute(
            select(Appointment).where(
                Appointment.contact_id == message.conversation.contact_id,
                Appointment.agent_id == message.agent_id,
                Appointment.created_at >= cutoff,
            )
        )
        fuzzy_appt = fuzzy_result.scalar_one_or_none()
        if fuzzy_appt:
            # Backfill the message_id link
            fuzzy_appt.message_id = message.id
            log.info(
                "reconciled_booking_via_fuzzy_match",
                appointment_id=fuzzy_appt.id,
            )
            return "success"

    return None


async def handle_call_hangup(payload: dict[Any, Any], log: Any) -> None:  # noqa: PLR0912, PLR0915
    """Handle call hangup event."""
    call_control_id = payload.get("call_control_id", "")
    duration_secs = payload.get("duration_seconds", 0)
    hangup_cause = payload.get("hangup_cause", "")
    hangup_source = payload.get("hangup_source", "")

    log = log.bind(
        call_control_id=call_control_id,
        duration=duration_secs,
        hangup_cause=hangup_cause,
        hangup_source=hangup_source,
    )
    log.info("call_hangup")

    # User-mode call: tear down the peer leg before the normal classification
    # path runs, so a half-connected call never leaves a live leg billing.
    await _teardown_user_call_peer_leg(call_control_id, log)

    async with AsyncSessionLocal() as db:
        from app.models.conversation import Message, MessageStatus

        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_control_id)
        )
        message = result.scalar_one_or_none()

        if message:
            if message.direction == "inbound" and message.conversation is not None:
                await release_inbound_call_capacity(
                    workspace_id=str(message.conversation.workspace_id),
                    call_control_id=call_control_id,
                )
            # Capture status BEFORE any mutation so we can detect whether
            # this is the first hangup transition or a Telnyx retry. Retries
            # must not double-count engagement / campaign stats.
            prior_status = message.status
            already_finalized = prior_status in _TERMINAL_HANGUP_STATUSES
            if already_finalized:
                log.info(
                    "hangup_retry_detected",
                    message_id=str(message.id),
                    prior_status=prior_status,
                )

            # Reconcile booking outcome before classification
            reconciled = await _reconcile_booking_outcome(db, message, log)
            if reconciled and not message.booking_outcome:
                message.booking_outcome = reconciled
            # Use stored streaming duration if hangup reports 0
            # (Telnyx doesn't populate duration_seconds for streaming/WebSocket calls)
            if duration_secs > 0:
                message.duration_seconds = duration_secs
            elif message.duration_seconds and message.duration_seconds > 0:
                duration_secs = message.duration_seconds
            else:
                message.duration_seconds = duration_secs

            # The AI-first pilot never retains raw provider recordings.
            recordings = payload.get("recordings", [])
            if recordings and message.voice_disclosure_status is None:
                message.recording_url = recordings[0].get("public_url")
                log.info("recording_available")
            elif recordings:
                log.warning("unexpected_inbound_ai_recording_ignored")

            # Classify the call outcome
            classification = _call_classifier.classify(
                hangup_cause=hangup_cause,
                duration_secs=duration_secs,
                hangup_source=hangup_source,
                booking_outcome=message.booking_outcome,
            )

            message.status = classification.message_status

            # Store error info for failed calls
            if classification.error_code:
                message.error_code = classification.error_code
                message.error_message = classification.error_message

            if classification.is_rejection:
                log.info("rejected_call_detected", hangup_source=hangup_source)

            # Override if booking was successful
            if (
                message.booking_outcome == "success"
                and classification.message_status == MessageStatus.FAILED
            ):
                log.info("overriding_failed_status_due_to_successful_booking")
                message.status = MessageStatus.COMPLETED

            await db.commit()
            log.info("message_updated", message_id=str(message.id), status=message.status)

            # Record completion metric exactly once per call (skip retries that
            # arrive after we've already finalised the message status).
            if not already_finalized:
                workspace_id = message.conversation.workspace_id if message.conversation else None
                observe_voice_call_completed(
                    workspace_id=workspace_id,
                    outcome=str(message.status),
                    duration_seconds=message.duration_seconds or duration_secs,
                )
                if message.voice_disclosure_status is not None:
                    pilot_duration = message.duration_seconds or duration_secs
                    observe_inbound_call_summary(
                        workspace_id=workspace_id,
                        duration_seconds=pilot_duration,
                        estimated_cost_usd=(
                            max(float(pilot_duration), 0)
                            / 60
                            * settings.inbound_voice_estimated_cost_per_minute_usd
                        ),
                    )

            contact_id = message.conversation.contact_id if message.conversation else None
            duration = message.duration_seconds or 0
            if contact_id and duration > 0 and not already_finalized:
                try:
                    from app.services.contacts.engagement_score import record_engagement

                    await record_engagement(db, contact_id)
                    await db.commit()
                except Exception as e:
                    log.warning("engagement_update_failed", error_type=type(e).__name__)
            elif already_finalized:
                log.info("engagement_update_skipped_retry")

            # Push notification for missed/failed inbound calls
            if message.direction == "inbound" and message.status in ("no_answer", "failed"):
                try:
                    from_number, _ = extract_phone_numbers(payload)
                    workspace_id = (
                        message.conversation.workspace_id if message.conversation else None
                    )
                    if workspace_id:
                        await push_notification_service.send_to_workspace_members(
                            db=db,
                            workspace_id=str(workspace_id),
                            title="Missed Call",
                            body=from_number,
                            data={
                                "type": "missed_call",
                                "messageId": str(message.id),
                                "screen": f"/(tabs)/calls/{message.id}",
                            },
                            notification_type="call",
                            channel_id="calls",
                        )
                except Exception as e:
                    log.error("push_notification_failed", error_type=type(e).__name__)

            # Create CallOutcome record for attribution and analysis
            try:
                from app.services.ai.call_outcome_service import create_outcome_from_hangup

                await create_outcome_from_hangup(
                    db=db,
                    message_id=message.id,
                    hangup_cause=hangup_cause,
                    duration_secs=duration_secs,
                    booking_outcome=message.booking_outcome,
                )
                log.info("call_outcome_created", message_id=str(message.id))
            except Exception as e:
                log.error("call_outcome_creation_failed", error_type=type(e).__name__)

            # Update campaign stats for ALL calls (successful and failed),
            # but only on the first hangup transition. Telnyx retries arrive
            # with the same call_control_id and would otherwise inflate
            # campaign call counters.
            if not already_finalized:
                try:
                    from app.services.campaigns.campaign_call_stats import (
                        update_campaign_call_stats,
                    )

                    await update_campaign_call_stats(
                        db=db,
                        message_id=message.id,
                        call_outcome=classification.outcome,
                        message_status=classification.message_status,
                        duration_secs=duration_secs,
                        log=log,
                        booking_outcome=message.booking_outcome,
                    )
                except Exception as e:
                    log.error("campaign_call_stats_update_failed", error_type=type(e).__name__)
            else:
                log.info("campaign_call_stats_skipped_retry")

            # Trigger SMS fallback for failed calls only
            if classification.outcome:
                log.info("triggering_sms_fallback", call_outcome=classification.outcome)
                try:
                    from app.services.campaigns.sms_fallback import trigger_sms_fallback_for_call

                    await trigger_sms_fallback_for_call(
                        call_control_id=call_control_id,
                        call_outcome=classification.outcome,
                        log=log,
                    )
                except Exception as e:
                    log.error("sms_fallback_trigger_failed", error_type=type(e).__name__)

            # Automatic missed-call text-back: for unanswered INBOUND calls,
            # invite the caller to book via SMS. The service is idempotent on
            # call_control_id and only acts when the workspace has opted in, so
            # it is safe to call on every hangup (including Telnyx retries).
            if classification.outcome and message.direction == "inbound":
                try:
                    from app.services.telephony.missed_call_textback import (
                        send_missed_call_textback,
                    )

                    await send_missed_call_textback(
                        call_control_id=call_control_id,
                        call_outcome=classification.outcome,
                        log=log,
                    )
                except Exception as e:
                    log.error("missed_call_textback_failed", error_type=type(e).__name__)


async def _handle_transfer_leg_answered(call_control_id: str, log: Any) -> bool:
    """Speak the warm-transfer briefing when the human closer's leg answers.

    Returns True when this leg is a pending warm-transfer closer leg (handled
    here), so the caller flow knows to short-circuit normal AI streaming.
    """
    from app.services.telephony.call_transfer import peek_pending_transfer
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    pending = await peek_pending_transfer(call_control_id)
    if pending is None:
        return False

    log.info("transfer_closer_leg_answered", closer_call_control_id=call_control_id)
    if not settings.telnyx_api_key:
        log.error("no_telnyx_api_key_for_transfer_briefing")
        return True

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        # Speak the briefing on the closer leg. The bridge happens once the
        # spoken briefing completes (call.speak.ended -> handle_speak_ended).
        spoke = await voice_service.speak_text(
            call_control_id=call_control_id,
            text=pending.briefing,
            language=pending.language,
        )
        if not spoke:
            # If we can't brief, bridge immediately so the caller still reaches
            # a human rather than getting stuck on a parked leg.
            log.warning("transfer_briefing_failed_bridging_now")
            await voice_service.bridge_calls(
                call_control_id=call_control_id,
                other_call_control_id=pending.caller_call_control_id,
            )
    except Exception as e:
        log.error("transfer_leg_answered_error", error_type=type(e).__name__)
    finally:
        await voice_service.close()
    return True


async def _teardown_user_call_peer_leg(call_control_id: str, log: Any) -> None:
    """Hang up the surviving leg of a user-mode call and clear its Redis state.

    Called for every ``call.hangup``; a no-op unless the leg belongs to a live
    user call. Both directions are handled: the rep bailing while the contact
    rings must not leave the contact connected to nobody, and vice versa.
    """
    from app.models.conversation import Message, MessageStatus
    from app.services.telephony.telnyx_voice import TelnyxVoiceService
    from app.services.telephony.user_call import STAGE_BRIDGED, pop_pending_user_call

    pending = await pop_pending_user_call(call_control_id)
    if pending is None:
        return

    peer = pending.peer_of(call_control_id)
    log.info(
        "user_call_leg_hangup",
        message_id=pending.message_id,
        stage=pending.stage,
        peer_call_control_id=peer,
    )

    if peer and settings.telnyx_api_key:
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            await voice_service.hangup_call(peer)
        except Exception as e:  # pragma: no cover - teardown is best-effort
            log.warning("user_call_peer_hangup_failed", error_type=type(e).__name__)
        finally:
            await voice_service.close()

    # The rep dropping before the bridge means the call never happened. The
    # Message may already point at the contact leg, whose own hangup webhook
    # would otherwise be the only thing to finalise it.
    if call_control_id == pending.rep_call_control_id and pending.stage != STAGE_BRIDGED:
        async with AsyncSessionLocal() as db:
            message = await db.get(Message, uuid.UUID(pending.message_id))
            if message is not None and message.status not in _TERMINAL_HANGUP_STATUSES:
                message.status = MessageStatus.FAILED
                message.error_code = "USER_CALL_REP_HUNG_UP"
                message.error_message = "Caller hung up before the contact answered."
                await db.commit()


async def _handle_user_call_leg_answered(
    call_control_id: str,
    log: Any,
    *,
    client_state: str | None = None,
) -> bool:
    """Advance a user-mode call when one of its two legs answers.

    Rep leg answered -> dial the contact and repoint the ``Message`` at that new
    leg. Contact leg answered -> bridge the two legs and mark the call answered.

    Returns True when this leg belongs to a user call (handled here), so the
    caller short-circuits normal AI streaming.
    """
    from app.services.telephony.telnyx_voice import TelnyxVoiceService
    from app.services.telephony.user_call import (
        decode_user_call_client_state,
        peek_pending_user_call,
        pop_pending_user_call,
    )

    pending = await peek_pending_user_call(call_control_id)
    if pending is None:
        # Redis state is best-effort, but ``client_state`` round-trips through
        # Telnyx on every webhook for the leg, so it still identifies a user
        # call whose pending state expired or was lost. Without that state we
        # cannot bridge anything, and a live leg with nobody on it bills by the
        # minute — hang it up instead of parking it.
        if decode_user_call_client_state(client_state) is None:
            return False
        log.error("user_call_state_lost_hanging_up", call_control_id=call_control_id)
        if settings.telnyx_api_key:
            orphan_service = TelnyxVoiceService(settings.telnyx_api_key)
            try:
                await orphan_service.hangup_call(call_control_id)
            finally:
                await orphan_service.close()
        return True

    if not settings.telnyx_api_key:
        log.error("no_telnyx_api_key_for_user_call")
        return True

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        if call_control_id == pending.rep_call_control_id:
            if pending.contact_call_control_id:
                # Telnyx retried call.answered for the rep leg; the contact leg
                # is already dialed, so do not dial the contact twice.
                log.info("user_call_rep_leg_answered_duplicate")
            else:
                await _dial_user_call_contact_leg(voice_service, pending, log)
        elif call_control_id == pending.contact_call_control_id:
            await _bridge_user_call_legs(voice_service, pending, log)
    except Exception as e:
        log.error("user_call_leg_answered_error", error_type=type(e).__name__)
        await pop_pending_user_call(call_control_id)
    finally:
        await voice_service.close()
    return True


async def _dial_user_call_contact_leg(voice_service: Any, pending: Any, log: Any) -> None:
    """Rep picked up: dial the contact and re-anchor the Message on that leg."""
    from app.models.conversation import Message, MessageStatus
    from app.services.telephony.user_call import (
        CONTACT_LEG_TIMEOUT_SECONDS,
        make_user_call_leg_client_state,
        pop_pending_user_call,
        store_pending_user_call,
    )

    api_base = settings.api_base_url or "https://example.com"
    webhook_url = f"{api_base}/webhooks/telnyx/voice"
    connection_id = settings.telnyx_connection_id or (
        await voice_service.get_call_control_application_id(webhook_url)
    )

    contact_ccid = await voice_service.dial_transfer_leg(
        to_number=pending.contact_number,
        from_number=pending.from_number,
        connection_id=connection_id,
        webhook_url=webhook_url,
        client_state=make_user_call_leg_client_state(pending.message_id),
        timeout_secs=CONTACT_LEG_TIMEOUT_SECONDS,
    )

    if not contact_ccid:
        log.error("user_call_contact_dial_failed", message_id=pending.message_id)
        await pop_pending_user_call(pending.rep_call_control_id)
        await voice_service.hangup_call(pending.rep_call_control_id)
        async with AsyncSessionLocal() as db:
            message = await db.get(Message, uuid.UUID(pending.message_id))
            if message is not None:
                message.status = MessageStatus.FAILED
                message.error_code = "USER_CALL_CONTACT_DIAL_FAILED"
                message.error_message = "Could not dial the contact."
                await db.commit()
        return

    await store_pending_user_call(pending.with_contact_leg(contact_ccid))

    # Re-anchor the call on the contact leg so hangup, duration, recording, and
    # call history behave exactly like an AI call.
    async with AsyncSessionLocal() as db:
        message = await db.get(Message, uuid.UUID(pending.message_id))
        if message is not None:
            message.provider_message_id = contact_ccid
            await db.commit()

    log.info(
        "user_call_contact_leg_dialed",
        message_id=pending.message_id,
        contact_call_control_id=contact_ccid,
    )


async def _bridge_user_call_legs(voice_service: Any, pending: Any, log: Any) -> None:
    """Contact picked up: bridge them to the waiting rep, then record if enabled."""
    from app.models.conversation import Message, MessageStatus
    from app.models.workspace import Workspace
    from app.services.telephony.user_call import (
        USER_CALL_RECORDING_SETTINGS_KEY,
        pop_pending_user_call,
        store_pending_user_call,
    )

    contact_ccid = pending.contact_call_control_id
    bridged = await voice_service.bridge_calls(
        call_control_id=contact_ccid,
        other_call_control_id=pending.rep_call_control_id,
    )
    if not bridged:
        # Two live legs that can't be joined are pure spend — drop both.
        log.error("user_call_bridge_failed", message_id=pending.message_id)
        await pop_pending_user_call(contact_ccid)
        await voice_service.hangup_call(pending.rep_call_control_id)
        await voice_service.hangup_call(contact_ccid)
        return

    await store_pending_user_call(pending.bridged())
    log.info("user_call_bridged", message_id=pending.message_id)

    record = False
    async with AsyncSessionLocal() as db:
        message = await db.get(Message, uuid.UUID(pending.message_id))
        if message is not None:
            message.status = MessageStatus.ANSWERED
            await db.commit()

        workspace = await db.get(Workspace, uuid.UUID(pending.workspace_id))
        if workspace is not None:
            record = bool((workspace.settings or {}).get(USER_CALL_RECORDING_SETTINGS_KEY))

    if record:
        recorded = await voice_service.start_recording(contact_ccid)
        if recorded:
            log.info("user_call_recording_started", message_id=pending.message_id)
        else:
            log.warning("user_call_recording_failed", message_id=pending.message_id)


async def _complete_inbound_disclosure(
    call_control_id: str,
    message_id: uuid.UUID,
    log: Any,
) -> bool:
    """Start OpenAI media only for the bound message after its notice finished."""
    from app.models.conversation import Message
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(
                Message.id == message_id,
                Message.provider_message_id == call_control_id,
                Message.direction == "inbound",
            )
        )
        message = result.scalar_one_or_none()
        if message is None or message.conversation is None:
            return False

        conversation = message.conversation
        phone_result = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.workspace_id == conversation.workspace_id,
                PhoneNumber.phone_number == conversation.workspace_phone,
            )
        )
        phone_record = phone_result.scalar_one_or_none()
        fallback_number = phone_record.inbound_fallback_number if phone_record else None
        readiness = None
        if phone_record is not None and phone_record.inbound_ai_enabled:
            readiness = await evaluate_inbound_call_readiness(
                db,
                workspace_id=conversation.workspace_id,
                phone_number=phone_record,
                assigned_agent_id=message.agent_id,
                fallback_number=fallback_number,
                transfer_destination_number=None,
            )

        locked_result = await db.execute(
            select(Message)
            .where(
                Message.id == message_id,
                Message.provider_message_id == call_control_id,
            )
            .with_for_update()
        )
        message = locked_result.scalar_one_or_none()
        if message is None:
            return False
        if message.voice_disclosure_status == "completed":
            log.info("inbound_disclosure_duplicate_skipped")
            return True
        if message.voice_disclosure_status != "speaking":
            return message.voice_disclosure_status == "failed"

        if readiness is None or not readiness.ready or readiness.agent is None:
            message.voice_disclosure_status = "failed"
            await db.commit()
            observe_inbound_disclosure(conversation.workspace_id, "failed")
            log.warning(
                "inbound_streaming_prerequisite_failed",
                blocked_checks=(
                    [check.code for check in readiness.checks if not check.ready]
                    if readiness is not None
                    else ["call_state"]
                ),
            )
            await _transfer_inbound_to_fallback(
                call_control_id,
                fallback_number,
                log,
                reason="streaming_prerequisite_failed",
            )
            return True

        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            streaming_started = await voice_service.start_audio_streaming(
                call_control_id=call_control_id,
                api_base_url=settings.api_base_url,
                is_outbound=False,
            )
        except Exception as exc:
            log.error(
                "inbound_streaming_start_error",
                error_type=type(exc).__name__,
            )
            streaming_started = False
        finally:
            await voice_service.close()

        if streaming_started:
            message.voice_disclosure_status = "completed"
            message.voice_disclosed_at = datetime.now(UTC)
            await db.commit()
            observe_inbound_disclosure(conversation.workspace_id, "completed")
            log.info(
                "inbound_disclosure_completed_streaming_started",
                disclosure_version=message.voice_disclosure_version,
            )
        else:
            message.voice_disclosure_status = "failed"
            await db.commit()
            observe_inbound_disclosure(conversation.workspace_id, "failed")
            await _transfer_inbound_to_fallback(
                call_control_id,
                fallback_number,
                log,
                reason="streaming_start_failed",
            )
        return True


async def handle_speak_ended(payload: dict[Any, Any], log: Any) -> None:
    """Finish warm-transfer, terminal-notice, or disclosure speech commands."""
    from app.services.telephony.call_transfer import pop_pending_transfer
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    call_control_id = payload.get("call_control_id", "")
    log = log.bind(call_control_id=call_control_id)

    pending = await pop_pending_transfer(call_control_id)
    if pending is None:
        notice = decode_inbound_terminal_state(payload.get("client_state"))
        if notice is not None:
            if settings.telnyx_api_key:
                voice_service = TelnyxVoiceService(settings.telnyx_api_key)
                try:
                    await voice_service.hangup_call(call_control_id)
                finally:
                    await voice_service.close()
            return

        message_id = decode_inbound_disclosure_state(payload.get("client_state"))
        if message_id is not None:
            await _complete_inbound_disclosure(call_control_id, message_id, log)
        return

    log.info(
        "transfer_briefing_ended_bridging",
        caller_call_control_id=pending.caller_call_control_id,
    )
    if not settings.telnyx_api_key:
        log.error("no_telnyx_api_key_for_transfer_bridge")
        return

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        bridged = await voice_service.bridge_calls(
            call_control_id=call_control_id,
            other_call_control_id=pending.caller_call_control_id,
        )
        if bridged:
            log.info("warm_transfer_bridged")
        else:
            log.error("warm_transfer_bridge_failed")
    except Exception as e:
        log.error("transfer_bridge_error", error_type=type(e).__name__)
    finally:
        await voice_service.close()


async def handle_machine_detection(payload: dict[Any, Any], log: Any) -> None:
    """Handle voicemail/machine detection result."""
    call_control_id = payload.get("call_control_id", "")
    result_type = payload.get("result", "")

    log = log.bind(call_control_id=call_control_id, detection_result=result_type)
    log.info("machine_detection_result")

    # Check if voicemail/machine detected
    call_outcome = _call_classifier.classify_machine_detection(result_type)
    if not call_outcome:
        return

    log.info("voicemail_detected_hanging_up")

    # Push notification for voicemail
    try:
        from app.models.conversation import Message

        async with AsyncSessionLocal() as push_db:
            msg_result = await push_db.execute(
                select(Message)
                .options(selectinload(Message.conversation))
                .where(Message.provider_message_id == call_control_id)
            )
            msg = msg_result.scalar_one_or_none()
            if msg and msg.conversation:
                from_number, _ = extract_phone_numbers(payload)
                await push_notification_service.send_to_workspace_members(
                    db=push_db,
                    workspace_id=str(msg.conversation.workspace_id),
                    title="New Voicemail",
                    body=from_number,
                    data={
                        "type": "voicemail",
                        "messageId": str(msg.id),
                        "screen": f"/(tabs)/calls/{msg.id}",
                    },
                    notification_type="voicemail",
                    channel_id="calls",
                )
    except Exception as e:
        log.error("push_notification_failed", error_type=type(e).__name__)

    # Hang up the call
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    if settings.telnyx_api_key:
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            await voice_service.hangup_call(call_control_id)
            log.info("call_hung_up_on_voicemail")
        except Exception as e:
            log.error("hangup_failed", error_type=type(e).__name__)
        finally:
            await voice_service.close()

        # Trigger SMS fallback
        try:
            from app.services.campaigns.sms_fallback import trigger_sms_fallback_for_call

            await trigger_sms_fallback_for_call(
                call_control_id=call_control_id,
                call_outcome=call_outcome,
                log=log,
            )
        except Exception as e:
            log.error("sms_fallback_trigger_failed", error_type=type(e).__name__)

        # Automatic missed-call text-back for voicemail-detected calls. The
        # service self-guards on inbound direction and is idempotent on
        # call_control_id, so it no-ops for outbound voicemails and never
        # double-texts if the subsequent call.hangup also triggers it.
        try:
            from app.services.telephony.missed_call_textback import (
                send_missed_call_textback,
            )

            await send_missed_call_textback(
                call_control_id=call_control_id,
                call_outcome=call_outcome,
                log=log,
            )
        except Exception as e:
            log.error("missed_call_textback_failed", error_type=type(e).__name__)


async def handle_recording_saved(payload: dict[Any, Any], log: Any) -> None:
    """Handle ``call.recording.saved`` — transcribe + run the voicemail pipeline.

    Idempotent: :func:`process_voicemail_recording` collapses duplicate Telnyx
    retries via a Redis claim plus a DB transcript guard. The follow-up pipeline
    (classify intent/urgency, create an opportunity, notify operators, optional
    callback/text-back) only runs for inbound voicemail captures; ordinary call
    recordings just get their transcript persisted.
    """
    from app.services.telephony.voicemail import (
        extract_recording_url,
        is_voicemail_client_state,
        process_voicemail_recording,
    )

    call_control_id = payload.get("call_control_id", "")
    client_state = payload.get("client_state")
    recording_url = extract_recording_url(payload)

    log = log.bind(call_control_id=call_control_id)
    log.info("processing_recording_saved", has_url=bool(recording_url))

    if not call_control_id or not recording_url:
        log.warning("recording_saved_missing_fields")
        return

    is_voicemail = is_voicemail_client_state(client_state)
    run_followup = is_voicemail

    # Fall back to message state: an inbound call that was never answered by a
    # human/AI and rolled to a recording is treated as a voicemail too.
    if not run_followup:
        from app.models.conversation import Message

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Message.direction, Message.status).where(
                    Message.provider_message_id == call_control_id
                )
            )
            row = result.first()
        if row is not None:
            direction, status = row
            run_followup = str(direction) == "inbound" and str(status) in (
                "ringing",
                "no_answer",
                "failed",
            )

    await process_voicemail_recording(
        call_control_id=call_control_id,
        recording_url=recording_url,
        run_followup=run_followup,
        log=log,
    )


async def take_inbound_voicemail(
    call_control_id: str,
    log: Any,
) -> None:
    """Answer an unattended inbound call and record a voicemail message.

    Used when no voice-capable agent is available to take an inbound call. We
    answer, speak a short greeting, and start a tagged voicemail recording. The
    resulting ``call.recording.saved`` webhook drives the AI voicemail pipeline.
    """
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    if not settings.telnyx_api_key:
        log.warning("no_telnyx_api_key_for_voicemail")
        return

    greeting = (
        "Sorry, we're unable to take your call right now. "
        "Please leave a message after the tone and we'll get back to you."
    )

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        answered = await voice_service.answer_call(call_control_id)
        if not answered:
            log.error("voicemail_answer_failed", call_control_id=call_control_id)
            return
        await voice_service.speak_text(call_control_id=call_control_id, text=greeting)
        recorded = await voice_service.start_voicemail_recording(call_control_id)
        if recorded:
            log.info("voicemail_recording_started", call_control_id=call_control_id)
        else:
            log.warning("voicemail_recording_failed", call_control_id=call_control_id)
    except Exception as e:
        log.error("take_inbound_voicemail_error", error_type=type(e).__name__)
    finally:
        await voice_service.close()


async def _reject_inbound_call(call_control_id: str, log: Any) -> None:
    """Hang up a screened-out (spam) inbound call before it is answered."""
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    if not settings.telnyx_api_key:
        log.warning("no_telnyx_api_key_for_spam_rejection")
        return

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        await voice_service.hangup_call(call_control_id)
        log.info("inbound_spam_call_hung_up", call_control_id=call_control_id)
    except Exception as e:
        log.error("inbound_spam_call_hangup_failed", error_type=type(e).__name__)
    finally:
        await voice_service.close()


async def _transfer_inbound_to_fallback(
    call_control_id: str,
    fallback_number: str | None,
    log: Any,
    *,
    reason: str,
) -> None:
    """Transfer through the shared fallback service or play an unavailable notice."""
    from app.services.telephony.inbound_fallback import route_inbound_to_fallback

    await route_inbound_to_fallback(
        call_control_id=call_control_id,
        fallback_number=fallback_number,
        log=log,
        reason=reason,
    )


async def _resolve_ready_inbound_agent(
    call_control_id: str,
    phone_record: PhoneNumber,
    conversation: Any,
    log: Any,
    *,
    reason: str | None,
    caller_phone: str,
) -> Any | None:
    """Reserve spend/capacity, then resolve and validate the actual routed agent."""
    from app.services.telephony.inbound_fallback import end_inbound_call_with_notice

    try:
        await enforce_inbound_call_limits(
            workspace_id=str(phone_record.workspace_id),
            caller_phone=caller_phone,
        )
        await reserve_inbound_call_capacity(
            workspace_id=str(phone_record.workspace_id),
            call_control_id=call_control_id,
        )
    except InboundCallerRateLimitError:
        await end_inbound_call_with_notice(
            call_control_id=call_control_id,
            notice="busy",
            log=log,
            reason="caller_limit_reached",
        )
        return None
    except (SoftphoneRateLimitError, SoftphoneRateLimitUnavailableError):
        await _transfer_inbound_to_fallback(
            call_control_id,
            phone_record.inbound_fallback_number,
            log,
            reason="workspace_protection_blocked",
        )
        return None

    try:
        async with AsyncSessionLocal() as db:
            resolved = await _voice_agent_resolver.resolve(
                db, conversation, phone_record, log, reason=reason
            )
            if resolved is None:
                readiness = None
            else:
                readiness = await evaluate_inbound_call_readiness(
                    db,
                    workspace_id=phone_record.workspace_id,
                    phone_number=phone_record,
                    assigned_agent_id=resolved.agent.id,
                    fallback_number=phone_record.inbound_fallback_number,
                    transfer_destination_number=None,
                )
    except Exception as exc:
        log.error(
            "inbound_ai_readiness_error",
            error_type=type(exc).__name__,
        )
        await _transfer_inbound_to_fallback(
            call_control_id,
            phone_record.inbound_fallback_number,
            log,
            reason="readiness_error",
        )
        return None

    if resolved is None or readiness is None or not readiness.ready:
        blocked_checks = (
            [check.code for check in readiness.checks if not check.ready]
            if readiness is not None
            else ["agent"]
        )
        log.warning("inbound_ai_readiness_failed", blocked_checks=blocked_checks)
        await _transfer_inbound_to_fallback(
            call_control_id,
            phone_record.inbound_fallback_number,
            log,
            reason="agent_resolution_failed" if resolved is None else "ai_not_ready",
        )
        return None
    return resolved


async def _mark_inbound_disclosure_failed(message_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    from app.models.conversation import Message

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Message)
            .where(
                Message.id == message_id,
                Message.voice_disclosure_status.in_(("pending", "speaking")),
            )
            .values(voice_disclosure_status="failed")
        )
        await db.commit()
    observe_inbound_disclosure(workspace_id, "failed")


async def auto_answer_call_if_agent_assigned(
    call_control_id: str,
    phone_record: PhoneNumber,
    conversation: Any,
    log: Any,
    reason: str | None = None,
    caller_phone: str = "",
) -> None:
    """Route an allowlisted inbound call to disclosed AI or human fallback."""
    from app.models.conversation import Conversation, Message
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    if not phone_record.inbound_ai_enabled:
        await _transfer_inbound_to_fallback(
            call_control_id,
            phone_record.inbound_fallback_number,
            log,
            reason="ai_not_enabled",
        )
        return

    resolved = await _resolve_ready_inbound_agent(
        call_control_id,
        phone_record,
        conversation,
        log,
        reason=reason,
        caller_phone=caller_phone,
    )
    if resolved is None:
        return

    async with AsyncSessionLocal() as db:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation.id,
                Conversation.workspace_id == phone_record.workspace_id,
            )
        )
        conv = conv_result.scalar_one_or_none()
        message_result = await db.execute(
            select(Message).where(
                Message.provider_message_id == call_control_id,
                Message.conversation_id == conversation.id,
                Message.direction == "inbound",
            )
        )
        message = message_result.scalar_one_or_none()
        if conv is None or message is None:
            log.error("inbound_call_state_not_found")
            await _transfer_inbound_to_fallback(
                call_control_id,
                phone_record.inbound_fallback_number,
                log,
                reason="call_state_missing",
            )
            return

        conv.assigned_agent_id = resolved.agent.id
        conv.ai_enabled = True
        message_id = message.id
        message.agent_id = resolved.agent.id
        message.voice_disclosure_status = "pending"
        message.voice_disclosure_version = DISCLOSURE_VERSION
        await db.commit()

    if not settings.telnyx_api_key:
        await _mark_inbound_disclosure_failed(message_id, phone_record.workspace_id)
        await _transfer_inbound_to_fallback(
            call_control_id,
            phone_record.inbound_fallback_number,
            log,
            reason="telnyx_unavailable",
        )
        return

    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        answered = await voice_service.answer_call(call_control_id)
        if answered:
            log.info(
                "inbound_ai_call_answered_waiting_for_disclosure",
                agent_id=str(resolved.agent.id),
            )
            return
        log.error("failed_to_answer_inbound_ai_call")
    finally:
        await voice_service.close()

    await _mark_inbound_disclosure_failed(message_id, phone_record.workspace_id)
    await _transfer_inbound_to_fallback(
        call_control_id,
        phone_record.inbound_fallback_number,
        log,
        reason="answer_failed",
    )
