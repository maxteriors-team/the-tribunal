"""AI voicemail handling for inbound Telnyx calls.

When an inbound call rolls to voicemail (no agent answers) or the caller opts
to leave a message, the call is recorded via Telnyx. Once Telnyx delivers the
``call.recording.saved`` webhook, :func:`process_voicemail_recording` runs the
end-to-end pipeline:

1. Download the recording audio and transcribe it with a Whisper-compatible
   OpenAI model.
2. Persist the transcript on the call's :class:`Message` row by reusing
   :func:`app.services.ai.call_context.save_call_transcript`.
3. Classify the caller intent and urgency from the transcript.
4. Create a follow-up :class:`Opportunity` in the workspace's default pipeline.
5. Notify operators via push notification and email.
6. Optionally trigger an automated text-back and/or AI callback.

Safety rails:

* **Idempotent** — duplicate ``call.recording.saved`` deliveries (Telnyx retries
  on 5xx/timeout) are collapsed with a Redis ``SET NX`` claim keyed on the
  call + recording URL, plus a DB guard that skips when a transcript already
  exists for the call.
* **Signature-verified** — the webhook entrypoint
  (``app.api.webhooks.telnyx``) verifies the Telnyx ed25519 signature before
  any handler (including this pipeline) runs.
"""

from __future__ import annotations

import base64
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.conversation import Message, MessageChannel
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.workspace import Workspace
from app.services.ai.call_context import save_call_transcript
from app.services.idempotency import (
    claim_redis_idempotency_key,
    derive_outbound_key,
    derive_webhook_delivery_key,
)
from app.services.push_notifications import push_notification_service

logger = structlog.get_logger()

# Marker stored in Telnyx ``client_state`` when we begin a voicemail recording.
# Telnyx echoes ``client_state`` back on ``call.recording.saved`` so the webhook
# handler can distinguish a voicemail capture from an ordinary call recording.
_VOICEMAIL_CLIENT_STATE_TOKEN = "voicemail"

# Whisper-compatible transcription model.
_TRANSCRIBE_MODEL = "whisper-1"

# Chat model used for intent/urgency classification.
_CLASSIFY_MODEL = "gpt-4o-mini"

# Audio download guard: skip absurdly large payloads (~25 MB OpenAI limit).
_MAX_AUDIO_BYTES = 25 * 1024 * 1024

_ALLOWED_URGENCIES = ("low", "medium", "high")

_CLASSIFY_SYSTEM_PROMPT = (
    "You are a CRM assistant that triages voicemails left by inbound callers. "
    "Read the voicemail transcript and return structured JSON. Always return "
    "valid JSON."
)

_CLASSIFY_USER_PROMPT = (
    "Classify this voicemail transcript. Return a JSON object with exactly "
    "these fields:\n"
    '- "intent": short snake_case label for what the caller wants '
    '(e.g. "book_appointment", "pricing_question", "support_request", '
    '"callback_request", "spam", "other")\n'
    '- "urgency": one of "low", "medium", "high"\n'
    '- "summary": 1-2 sentence plain-English summary\n'
    '- "callback_requested": boolean, true if the caller asked to be called '
    "back\n\n"
    "TRANSCRIPT:\n{transcript}"
)


@dataclass(frozen=True, slots=True)
class VoicemailAnalysis:
    """Structured triage signals extracted from a voicemail transcript."""

    intent: str
    urgency: str
    summary: str
    callback_requested: bool


def encode_voicemail_client_state() -> str:
    """Return the base64 Telnyx ``client_state`` marking a voicemail recording."""
    return base64.b64encode(_VOICEMAIL_CLIENT_STATE_TOKEN.encode("ascii")).decode("ascii")


def is_voicemail_client_state(raw: str | None) -> bool:
    """Return True when ``raw`` is the base64 voicemail client_state marker."""
    if not raw:
        return False
    try:
        decoded = base64.b64decode(raw).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return False
    return decoded == _VOICEMAIL_CLIENT_STATE_TOKEN


def extract_recording_url(payload: dict[str, Any]) -> str | None:
    """Pull the best playable recording URL from a ``call.recording.saved`` payload.

    Prefers the public MP3 URL, falling back to authenticated/WAV variants.
    """
    for key in ("public_recording_urls", "recording_urls"):
        urls = payload.get(key)
        if isinstance(urls, dict):
            for fmt in ("mp3", "wav"):
                url = urls.get(fmt)
                if isinstance(url, str) and url:
                    return url
    # Some payloads carry a flat ``recordings`` array (as on call.hangup).
    recordings = payload.get("recordings")
    if isinstance(recordings, list) and recordings:
        first = recordings[0]
        if isinstance(first, dict):
            url = first.get("public_url") or first.get("url")
            if isinstance(url, str) and url:
                return url
    return None


async def transcribe_recording(
    audio_bytes: bytes,
    *,
    filename: str = "voicemail.mp3",
    log: Any,
) -> str:
    """Transcribe recording audio using a Whisper-compatible OpenAI model.

    Returns the transcript text, or an empty string on failure.
    """
    from app.services.ai.openai_credentials import create_openai_client

    if not audio_bytes:
        return ""

    try:
        client = create_openai_client()
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        response = await client.audio.transcriptions.create(
            model=_TRANSCRIBE_MODEL,
            file=audio_file,
            response_format="text",
        )
        transcript = str(response).strip()
        log.info("voicemail_transcribed", transcript_length=len(transcript))
        return transcript
    except Exception as exc:
        log.exception("voicemail_transcription_failed", error=str(exc))
        return ""


async def classify_voicemail(transcript: str, log: Any) -> VoicemailAnalysis:
    """Classify caller intent and urgency from a voicemail transcript."""
    from app.services.ai.openai_credentials import create_openai_client

    fallback = VoicemailAnalysis(
        intent="other",
        urgency="medium",
        summary=transcript[:200],
        callback_requested=False,
    )
    if not transcript.strip():
        return fallback

    try:
        client = create_openai_client()
        response = await client.chat.completions.create(
            model=_CLASSIFY_MODEL,
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _CLASSIFY_USER_PROMPT.format(transcript=transcript),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        text = response.choices[0].message.content or "{}"
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raw = {}
    except Exception as exc:
        log.exception("voicemail_classification_failed", error=str(exc))
        return fallback

    urgency = str(raw.get("urgency", "medium")).lower()
    if urgency not in _ALLOWED_URGENCIES:
        urgency = "medium"

    intent = str(raw.get("intent") or "other").strip() or "other"
    summary = str(raw.get("summary") or "").strip() or transcript[:200]
    callback_requested = bool(raw.get("callback_requested", False))

    return VoicemailAnalysis(
        intent=intent,
        urgency=urgency,
        summary=summary,
        callback_requested=callback_requested,
    )


async def _download_recording(recording_url: str, log: Any) -> bytes:
    """Download recording audio, returning empty bytes on failure."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            response = await client.get(recording_url)
            response.raise_for_status()
            content = response.content
    except Exception as exc:
        log.warning("voicemail_download_failed", error=str(exc))
        return b""

    if len(content) > _MAX_AUDIO_BYTES:
        log.warning("voicemail_audio_too_large", bytes=len(content))
        return b""
    return content


async def _find_default_pipeline_stage(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> tuple[Pipeline, PipelineStage | None] | None:
    """Return the workspace's default (oldest active) pipeline and its first stage."""
    pipeline_result = await db.execute(
        select(Pipeline)
        .where(Pipeline.workspace_id == workspace_id, Pipeline.is_active.is_(True))
        .order_by(Pipeline.created_at.asc())
        .limit(1)
    )
    pipeline = pipeline_result.scalar_one_or_none()
    if pipeline is None:
        return None

    stage_result = await db.execute(
        select(PipelineStage)
        .where(PipelineStage.pipeline_id == pipeline.id)
        .order_by(PipelineStage.order.asc())
        .limit(1)
    )
    stage = stage_result.scalar_one_or_none()
    return pipeline, stage


async def _create_followup_opportunity(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int | None,
    contact_phone: str,
    analysis: VoicemailAnalysis,
    log: Any,
) -> Opportunity | None:
    """Create a follow-up opportunity in the default pipeline for a voicemail."""
    found = await _find_default_pipeline_stage(db, workspace_id)
    if found is None:
        log.info("voicemail_followup_no_pipeline", workspace_id=str(workspace_id))
        return None
    pipeline, stage = found

    name = f"Voicemail follow-up — {contact_phone}"
    opportunity = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        stage_id=stage.id if stage else None,
        primary_contact_id=contact_id,
        name=name[:255],
        description=(f"[{analysis.urgency.upper()} · {analysis.intent}] {analysis.summary}")[:2000],
        probability=stage.probability if stage else 0,
        source="voicemail",
        status="open",
    )
    db.add(opportunity)
    await db.flush()
    log.info(
        "voicemail_followup_opportunity_created",
        opportunity_id=str(opportunity.id),
        urgency=analysis.urgency,
        intent=analysis.intent,
    )
    return opportunity


async def _notify_operators(
    db: AsyncSession,
    *,
    workspace: Workspace,
    message: Message,
    contact_phone: str,
    analysis: VoicemailAnalysis,
    log: Any,
) -> None:
    """Notify operators of a new transcribed voicemail via push + email."""
    workspace_id = workspace.id
    title = f"New Voicemail ({analysis.urgency})"
    body = f"{contact_phone}: {analysis.summary}"[:300]

    try:
        await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=str(workspace_id),
            title=title,
            body=body,
            data={
                "type": "voicemail",
                "messageId": str(message.id),
                "intent": analysis.intent,
                "urgency": analysis.urgency,
                "screen": f"/(tabs)/calls/{message.id}",
            },
            notification_type="voicemail",
            channel_id="calls",
        )
    except Exception as exc:
        log.exception("voicemail_push_failed", error=str(exc))

    try:
        await _email_workspace_members(
            db,
            workspace=workspace,
            message=message,
            contact_phone=contact_phone,
            analysis=analysis,
            log=log,
        )
    except Exception as exc:
        log.exception("voicemail_email_failed", error=str(exc))


async def _email_workspace_members(
    db: AsyncSession,
    *,
    workspace: Workspace,
    message: Message,
    contact_phone: str,
    analysis: VoicemailAnalysis,
    log: Any,
) -> None:
    """Email opted-in global operators about the voicemail."""
    from app.services.email import send_voicemail_notification
    from app.services.notification_recipients import workspace_notification_email_users

    transcript_text = ""
    if message.transcript:
        try:
            parsed = json.loads(message.transcript)
            transcript_text = str(parsed.get("text", "")) if isinstance(parsed, dict) else ""
        except (ValueError, TypeError):
            transcript_text = ""

    members = await workspace_notification_email_users(db, workspace.id)
    sent = 0
    for user in members:
        if not user.notification_email or not user.email:
            continue
        idem = derive_outbound_key("voicemail_email", message.id, user.id)
        ok = await send_voicemail_notification(
            to_email=user.email,
            workspace_name=workspace.name,
            contact_phone=contact_phone,
            summary=analysis.summary,
            transcript=transcript_text,
            intent=analysis.intent,
            urgency=analysis.urgency,
            idempotency_key=idem,
        )
        sent += 1 if ok else 0
    log.info("voicemail_email_dispatched", recipients=sent)


async def _maybe_automated_response(
    *,
    call_control_id: str,
    workspace: Workspace,
    analysis: VoicemailAnalysis,
    log: Any,
) -> None:
    """Optionally text the caller back and/or trigger an AI callback.

    Text-back reuses the idempotent missed-call text-back service. The AI
    callback is opt-in per workspace (``settings["voicemail_ai_callback"]``) and
    only fires for high-urgency or explicit callback requests.
    """
    # Automatic text-back (idempotent + workspace-gated inside the service).
    try:
        from app.services.telephony.missed_call_textback import send_missed_call_textback

        await send_missed_call_textback(
            call_control_id=call_control_id,
            call_outcome="voicemail",
            log=log,
        )
    except Exception as exc:
        log.exception("voicemail_textback_failed", error=str(exc))

    # Optional AI callback — disabled unless the workspace opts in.
    cfg = (workspace.settings or {}).get("voicemail_ai_callback", {})
    if not isinstance(cfg, dict) or not cfg.get("enabled"):
        return
    if analysis.urgency != "high" and not analysis.callback_requested:
        log.info("voicemail_ai_callback_skipped_low_priority")
        return
    try:
        await _trigger_ai_callback(call_control_id=call_control_id, log=log)
    except Exception as exc:
        log.exception("voicemail_ai_callback_failed", error=str(exc))


async def _trigger_ai_callback(*, call_control_id: str, log: Any) -> None:
    """Originate an AI callback to the voicemail caller (best-effort)."""
    from app.core.config import settings
    from app.models.phone_number import PhoneNumber
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

    if not settings.telnyx_api_key:
        log.warning("voicemail_ai_callback_no_api_key")
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_control_id)
        )
        message = result.scalar_one_or_none()
        if message is None or message.conversation is None:
            return
        conversation = message.conversation
        # A voicemail always belongs to a phone-keyed thread; a Messenger thread
        # has no number to call back.
        contact_phone = conversation.contact_phone
        workspace_phone = conversation.workspace_phone
        if not contact_phone or not workspace_phone:
            log.info("voicemail_ai_callback_no_phone")
            return
        agent_id = conversation.assigned_agent_id
        if agent_id is None:
            phone_result = await db.execute(
                select(PhoneNumber.assigned_agent_id).where(
                    PhoneNumber.workspace_id == conversation.workspace_id,
                    PhoneNumber.phone_number == conversation.workspace_phone,
                )
            )
            agent_id = phone_result.scalar_one_or_none()
        if agent_id is None:
            log.info("voicemail_ai_callback_no_agent")
            return

        webhook_url = f"{settings.api_base_url}/webhooks/telnyx/voice"
        idem = derive_outbound_key("voicemail_callback", call_control_id)
        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        try:
            await voice_service.initiate_call(
                to_number=contact_phone,
                from_number=workspace_phone,
                connection_id=None,
                webhook_url=webhook_url,
                db=db,
                workspace_id=conversation.workspace_id,
                contact_phone=contact_phone,
                agent_id=agent_id,
                idempotency_key=idem,
            )
            log.info("voicemail_ai_callback_initiated")
        finally:
            await voice_service.close()


async def process_voicemail_recording(  # noqa: PLR0911
    call_control_id: str,
    recording_url: str | None,
    *,
    run_followup: bool,
    log: Any,
) -> bool:
    """Transcribe a saved recording and run the AI voicemail follow-up pipeline.

    Returns True when the voicemail was processed end-to-end, False when the
    work was skipped (duplicate delivery, missing message, no audio, etc.).
    """
    log = log.bind(call_control_id=call_control_id, voicemail=run_followup)

    if not recording_url:
        log.warning("voicemail_no_recording_url")
        return False

    # Idempotency: collapse duplicate ``call.recording.saved`` deliveries.
    claim_key = (
        derive_webhook_delivery_key("telnyx", "voicemail", call_control_id, recording_url)
        or f"telnyx:webhook:voicemail:{call_control_id}"
    )
    claim = await claim_redis_idempotency_key(claim_key, log=log)
    if not claim.claimed:
        log.info("voicemail_recording_duplicate_skipped")
        return False

    # Load the call's Message + conversation + workspace.
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_control_id)
        )
        message = result.scalar_one_or_none()
        if message is None or message.conversation is None:
            log.warning("voicemail_message_not_found")
            return False

        # DB guard: a transcript already present means a prior delivery (that
        # raced past the Redis claim, e.g. Redis was unavailable) processed it.
        if message.transcript:
            log.info("voicemail_transcript_already_present", message_id=str(message.id))
            return False

        conversation = message.conversation
        workspace_id = conversation.workspace_id
        contact_id = conversation.contact_id
        # A voicemail is always on a phone-keyed thread; the follow-up notice and
        # opportunity are both titled by the caller's number.
        contact_phone = conversation.contact_phone
        if not contact_phone:
            log.info("voicemail_no_contact_phone")
            return False
        message_id = message.id

        message.recording_url = recording_url
        if run_followup:
            message.channel = MessageChannel.VOICEMAIL
        await db.commit()

    # Download + transcribe.
    audio = await _download_recording(recording_url, log)
    transcript = await transcribe_recording(audio, log=log) if audio else ""

    # Persist the transcript on the Message row (reuses save_call_transcript).
    transcript_json = json.dumps(
        {
            "text": transcript,
            "source": "voicemail",
            "recording_url": recording_url,
            "transcribed_at": datetime.now(UTC).isoformat(),
        }
    )
    await save_call_transcript(call_control_id, transcript_json, log)

    if not run_followup:
        log.info("voicemail_recording_transcript_saved_no_followup")
        return True

    if not transcript:
        log.info("voicemail_empty_transcript_skipping_followup")
        return False

    analysis = await classify_voicemail(transcript, log)

    async with AsyncSessionLocal() as db:
        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            log.warning("voicemail_workspace_not_found")
            return False

        msg_result = await db.execute(select(Message).where(Message.id == message_id))
        message = msg_result.scalar_one_or_none()
        if message is None:
            return False

        await _create_followup_opportunity(
            db,
            workspace_id=workspace_id,
            contact_id=contact_id,
            contact_phone=contact_phone,
            analysis=analysis,
            log=log,
        )
        await db.commit()

        await _notify_operators(
            db,
            workspace=workspace,
            message=message,
            contact_phone=contact_phone,
            analysis=analysis,
            log=log,
        )

    await _maybe_automated_response(
        call_control_id=call_control_id,
        workspace=workspace,
        analysis=analysis,
        log=log,
    )

    log.info(
        "voicemail_processed",
        intent=analysis.intent,
        urgency=analysis.urgency,
        callback_requested=analysis.callback_requested,
    )
    return True
