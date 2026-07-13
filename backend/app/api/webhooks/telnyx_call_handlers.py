"""Telnyx voice call webhook handlers."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.webhooks.telnyx_parser import extract_phone_numbers
from app.core.config import settings
from app.core.metrics import (
    observe_voice_call_completed,
    observe_voice_call_started,
)
from app.db.session import AsyncSessionLocal
from app.models.phone_number import PhoneNumber
from app.services.push_notifications import push_notification_service
from app.services.telephony.call_outcome_classifier import CallOutcomeClassifier
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


async def handle_call_initiated(payload: dict[Any, Any], log: Any) -> None:  # noqa: PLR0915
    """Handle incoming call."""
    call_control_id = payload.get("call_control_id", "")
    call_state = payload.get("state", "")
    from_number, to_number = extract_phone_numbers(payload)

    log = log.bind(
        call_control_id=call_control_id,
        from_number=from_number,
        to_number=to_number,
        call_state=call_state,
    )
    log.info("processing_call_initiated")

    if not all([call_control_id, from_number, to_number]):
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

        # Create message record for incoming call
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

        # Get or create conversation
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.workspace_phone == to_number,
                Conversation.contact_phone == from_number,
            )
        )
        conversation = conv_result.scalar_one_or_none()

        if not conversation:
            from app.core.encryption import hash_phone
            from app.models.contact import Contact
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
                ai_enabled=True,
            )
            db.add(conversation)
            await db.flush()

        # Create inbound message
        message = Message(
            conversation_id=conversation.id,
            provider_message_id=call_control_id,
            direction="inbound",
            channel="voice",
            body="",
            status="ringing",
        )
        db.add(message)

        # Update conversation
        conversation.channel = "voice"
        conversation.last_message_preview = "Incoming call"
        conversation.last_message_at = datetime.now(UTC)

        # Speed-to-lead SLA: anchor the lead's first inbound touch (the call).
        from app.services.sla import mark_inbound_lead

        mark_inbound_lead(conversation)

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
                    "screen": f"/call/{message.id}",
                },
                notification_type="call",
                channel_id="calls",
            )
        except Exception as e:
            log.exception("push_notification_failed", error=str(e))

        # Screen-with-a-challenge: route suspicious callers to voicemail/identity
        # capture instead of engaging the AI agent. A human can review the
        # recording before any callback.
        if screening.needs_challenge:
            log.info(
                "inbound_call_challenged",
                screening_reason=screening.reason,
                call_control_id=call_control_id,
            )
            await take_inbound_voicemail(call_control_id, log)
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

    async with AsyncSessionLocal() as db:
        from app.models.conversation import Message, MessageStatus

        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_control_id)
        )
        message = result.scalar_one_or_none()

        if message:
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

            # Get recording URL if available
            recordings = payload.get("recordings", [])
            if recordings:
                message.recording_url = recordings[0].get("public_url")
                log.info("recording_available", recording_url=message.recording_url)

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

            contact_id = message.conversation.contact_id if message.conversation else None
            duration = message.duration_seconds or 0
            if contact_id and duration > 0 and not already_finalized:
                try:
                    from app.services.contacts.engagement_score import record_engagement

                    await record_engagement(db, contact_id)
                    await db.commit()
                except Exception as e:
                    log.warning("engagement_update_failed", error=str(e))
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
                    log.exception("push_notification_failed", error=str(e))

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
                log.exception("call_outcome_creation_failed", error=str(e))

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
                    log.exception("campaign_call_stats_update_failed", error=str(e))
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
                    log.exception("sms_fallback_trigger_failed", error=str(e))

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
                    log.exception("missed_call_textback_failed", error=str(e))


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
        log.exception("transfer_leg_answered_error", error=str(e))
    finally:
        await voice_service.close()
    return True


async def handle_speak_ended(payload: dict[Any, Any], log: Any) -> None:
    """Bridge the caller into the closer leg after the warm-transfer briefing.

    Fires on ``call.speak.ended``. For warm transfers, the closer leg has just
    finished hearing the briefing, so we bridge it to the original caller leg
    to complete the handoff. Non-transfer speak events are ignored.
    """
    from app.services.telephony.call_transfer import pop_pending_transfer
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    call_control_id = payload.get("call_control_id", "")
    log = log.bind(call_control_id=call_control_id)

    pending = await pop_pending_transfer(call_control_id)
    if pending is None:
        # Not a warm-transfer closer leg (e.g. an ordinary speak). Nothing to do.
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
        log.exception("transfer_bridge_error", error=str(e))
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
        log.exception("push_notification_failed", error=str(e))

    # Hang up the call
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    if settings.telnyx_api_key:
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            await voice_service.hangup_call(call_control_id)
            log.info("call_hung_up_on_voicemail")
        except Exception as e:
            log.exception("hangup_failed", error=str(e))
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
            log.exception("sms_fallback_trigger_failed", error=str(e))

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
            log.exception("missed_call_textback_failed", error=str(e))


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
        log.exception("take_inbound_voicemail_error", error=str(e))
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
        log.exception("inbound_spam_call_hangup_failed", error=str(e))
    finally:
        await voice_service.close()


async def auto_answer_call_if_agent_assigned(
    call_control_id: str,
    phone_record: PhoneNumber,
    conversation: Any,
    log: Any,
    reason: str | None = None,
) -> None:
    """Auto-answer incoming call if an active agent is assigned."""
    from app.models.conversation import Conversation
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    log.info(
        "========== AUTO ANSWER CHECK ==========",
        call_control_id=call_control_id,
        phone_number=phone_record.phone_number,
        phone_assigned_agent_id=str(phone_record.assigned_agent_id)
        if phone_record.assigned_agent_id
        else None,
        conversation_id=str(conversation.id) if conversation else None,
    )

    if not settings.telnyx_api_key:
        log.warning("no_telnyx_api_key_for_auto_answer")
        return

    async with AsyncSessionLocal() as db:
        resolved = await _voice_agent_resolver.resolve(
            db, conversation, phone_record, log, reason=reason
        )

        if not resolved:
            log.info(
                "no_valid_voice_agent_found",
                phone_number=phone_record.phone_number,
                hint="Assign a voice-capable agent to the phone number or campaign",
            )
            # No agent available to take the call — answer it ourselves and
            # record a voicemail so the caller can still leave a message. The
            # recording webhook then runs the AI voicemail pipeline.
            await take_inbound_voicemail(call_control_id, log)
            return

        log.info(
            "auto_answering_call_with_agent",
            agent_id=str(resolved.agent.id),
            agent_name=resolved.agent.name,
            agent_source=resolved.source,
            routing_reason=resolved.reason,
            call_control_id=call_control_id,
        )

        # Update conversation with assigned agent
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == conversation.id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv:
            conv.assigned_agent_id = resolved.agent.id
            conv.ai_enabled = True
            await db.commit()

        # Answer the call via Telnyx
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            answered = await voice_service.answer_call(call_control_id)

            if not answered:
                log.error("failed_to_answer_call", call_control_id=call_control_id)
                return

            log.info("call_answered_successfully", call_control_id=call_control_id)

            # Start audio streaming
            api_base = settings.api_base_url or "https://example.com"
            streaming_started = await voice_service.start_audio_streaming(
                call_control_id=call_control_id,
                api_base_url=api_base,
                is_outbound=False,
            )

            if streaming_started:
                log.info("audio_streaming_started", call_control_id=call_control_id)
            else:
                log.error("failed_to_start_audio_streaming", call_control_id=call_control_id)

            # Start recording if agent has it enabled
            if resolved.agent.enable_recording:
                recorded = await voice_service.start_recording(call_control_id)
                if recorded:
                    log.info("call_recording_started", call_control_id=call_control_id)
                else:
                    log.warning("call_recording_failed", call_control_id=call_control_id)

        finally:
            await voice_service.close()
