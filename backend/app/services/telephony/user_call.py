"""Operator ("user mode") outbound calls: ring the rep, then bridge the contact.

An AI-mode outbound call is a single leg: we dial the contact and stream the
audio to a voice agent. A user-mode call has no agent — a human operator wants
to talk — so it needs *two* legs we control end to end:

1. Leg A rings the rep's own phone from the workspace caller ID.
2. When the rep answers, leg B dials the contact.
3. When the contact answers, the two legs are bridged.

Both legs are originated by us, so both ``call_control_id``s are ours and the
handshake is completed by the Telnyx voice webhook handler using pending state
stashed here in Redis (same shape as :mod:`app.services.telephony.call_transfer`).
Webhooks can land on any backend replica, so this state must never live in
process memory.

The ``Message`` row is anchored on the **contact** leg, which keeps hangup,
duration, recording, transcript, and call-history semantics identical to AI
calls.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import observe_voice_call_started
from app.db.redis import get_redis
from app.db.scope import apply_workspace_scope
from app.models.conversation import Message, MessageStatus
from app.models.phone_number import PhoneNumber
from app.utils.phone import normalize_phone_safe

if TYPE_CHECKING:
    from app.services.telephony.telnyx_voice import TelnyxVoiceService

logger = structlog.get_logger()

# Redis key prefix for user-call pending state. The state is written under
# *both* leg ids so a webhook for either leg resolves it with one lookup.
_PENDING_USER_CALL_PREFIX = "voice:usercall:pending:"
_PENDING_USER_CALL_TTL_SECONDS = 600  # 10 minutes; a call setup resolves fast

# client_state marker so user-call leg webhooks stay recognisable even when the
# Redis state is gone. Telnyx echoes client_state on every webhook for the leg,
# so this is the one piece of cross-replica state that cannot be lost.
USER_CALL_LEG_CLIENT_STATE_PREFIX = "user_call"

# Ring timeouts. Every user-mode call is two billable legs, so both are capped.
REP_LEG_TIMEOUT_SECONDS = 25
CONTACT_LEG_TIMEOUT_SECONDS = 30

# Workspace ``settings`` flag opting into recording operator calls. Off by
# default: a rep-to-customer call is two humans talking, and recording consent
# rules vary by state, so this stays an explicit operator decision.
USER_CALL_RECORDING_SETTINGS_KEY = "record_user_calls"

# Stages of the dial -> dial -> bridge handshake.
STAGE_DIALING_REP = "dialing_rep"
STAGE_DIALING_CONTACT = "dialing_contact"
STAGE_BRIDGED = "bridged"


@dataclass(frozen=True, slots=True)
class PendingUserCall:
    """State bridging the rep-leg -> contact-leg -> bridge handshake.

    Stored in Redis under the rep leg id and (once dialed) the contact leg id.
    The voice webhook handler reads it on ``call.answered`` for either leg and
    on ``call.hangup`` to tear down the surviving peer leg.
    """

    rep_call_control_id: str
    contact_call_control_id: str | None
    message_id: str
    workspace_id: str
    user_id: str
    contact_number: str
    from_number: str
    stage: str
    created_at: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "rep_call_control_id": self.rep_call_control_id,
                "contact_call_control_id": self.contact_call_control_id,
                "message_id": self.message_id,
                "workspace_id": self.workspace_id,
                "user_id": self.user_id,
                "contact_number": self.contact_number,
                "from_number": self.from_number,
                "stage": self.stage,
                "created_at": self.created_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> PendingUserCall:
        data = json.loads(raw)
        return cls(
            rep_call_control_id=data["rep_call_control_id"],
            contact_call_control_id=data.get("contact_call_control_id"),
            message_id=data["message_id"],
            workspace_id=data["workspace_id"],
            user_id=data["user_id"],
            contact_number=data["contact_number"],
            from_number=data["from_number"],
            stage=data.get("stage", STAGE_DIALING_REP),
            created_at=data.get("created_at", ""),
        )

    def with_contact_leg(self, contact_call_control_id: str) -> PendingUserCall:
        """Return a copy advanced to the contact-leg stage."""
        return replace(
            self,
            contact_call_control_id=contact_call_control_id,
            stage=STAGE_DIALING_CONTACT,
        )

    def bridged(self) -> PendingUserCall:
        """Return a copy marked as bridged (both legs live and merged)."""
        return replace(self, stage=STAGE_BRIDGED)

    def peer_of(self, call_control_id: str) -> str | None:
        """Return the other leg's id for ``call_control_id``, if there is one."""
        if call_control_id == self.rep_call_control_id:
            return self.contact_call_control_id
        if call_control_id == self.contact_call_control_id:
            return self.rep_call_control_id
        return None


def make_user_call_leg_client_state(message_id: Any) -> str:
    """Return base64 ``client_state`` marking a leg as part of a user call."""
    raw = f"{USER_CALL_LEG_CLIENT_STATE_PREFIX}:{message_id}"
    return base64.b64encode(raw.encode("ascii")).decode("ascii")


def decode_user_call_client_state(raw: str | None) -> str | None:
    """Return the message id encoded in a user-call ``client_state``.

    Returns None when ``raw`` is absent or is not a user-call marker (e.g. the
    plain idempotency-key client_state used by ordinary AI calls).
    """
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    prefix = f"{USER_CALL_LEG_CLIENT_STATE_PREFIX}:"
    if not decoded.startswith(prefix):
        return None
    return decoded[len(prefix) :] or None


def _keys_for(pending: PendingUserCall) -> list[str]:
    keys = [_PENDING_USER_CALL_PREFIX + pending.rep_call_control_id]
    if pending.contact_call_control_id:
        keys.append(_PENDING_USER_CALL_PREFIX + pending.contact_call_control_id)
    return keys


async def store_pending_user_call(pending: PendingUserCall) -> None:
    """Persist user-call state under every known leg id."""
    try:
        client = await get_redis()
        payload = pending.to_json()
        for key in _keys_for(pending):
            await client.set(key, payload, ex=_PENDING_USER_CALL_TTL_SECONDS)
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("store_pending_user_call_failed", error=str(exc))


async def peek_pending_user_call(call_control_id: str) -> PendingUserCall | None:
    """Read user-call state for either leg without deleting it."""
    try:
        client = await get_redis()
        raw = await client.get(_PENDING_USER_CALL_PREFIX + call_control_id)
        return PendingUserCall.from_json(raw) if raw is not None else None
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("peek_pending_user_call_failed", error=str(exc))
        return None


async def pop_pending_user_call(call_control_id: str) -> PendingUserCall | None:
    """Fetch user-call state for either leg and delete it for *both* legs."""
    try:
        client = await get_redis()
        raw = await client.get(_PENDING_USER_CALL_PREFIX + call_control_id)
        if raw is None:
            return None
        pending = PendingUserCall.from_json(raw)
        for key in _keys_for(pending):
            await client.delete(key)
        return pending
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("pop_pending_user_call_failed", error=str(exc))
        return None


class VoiceProviderUnavailableError(RuntimeError):
    """Telnyx could not give us a connection to originate legs on.

    Raised instead of letting the provider's ``ValueError`` escape as a 500:
    a misconfigured Call Control Application is an operator problem with a
    clear fix, not an unexpected server fault.
    """


class RepNumberNotAllowedError(ValueError):
    """The requested rep callback number is not on the workspace allowlist.

    User-mode calls bill the workspace for a leg to whatever number the client
    asks us to ring. A free-form E.164 would let any member with comms-send
    permission dial premium-rate or international destinations on the
    workspace's dime, so the number must resolve to something the workspace
    already owns or has configured.
    """


async def resolve_rep_callback_number(
    db: AsyncSession,
    user: Any,
    workspace: Any,
    requested: str | None,
) -> str:
    """Resolve (and authorise) the number that rings the human operator.

    The allowlist, in preference order:

    1. The calling user's own ``User.phone_number``.
    2. The workspace ``settings["transfer_destination_number"]`` (the same
       number AI warm transfers hand off to).
    3. Any voice-enabled phone number the workspace owns.

    Args:
        db: Database session.
        user: The authenticated ``User`` placing the call.
        workspace: The ``Workspace`` the call is billed to.
        requested: Client-supplied callback number, or None to auto-select.

    Returns:
        The allowlisted callback number in E.164.

    Raises:
        RepNumberNotAllowedError: When ``requested`` is off-allowlist, or when
            no callback number is configured at all.
    """
    candidates: list[str] = []

    user_phone = normalize_phone_safe(getattr(user, "phone_number", None) or "")
    if user_phone:
        candidates.append(user_phone)

    ws_settings = getattr(workspace, "settings", None) or {}
    transfer_number = normalize_phone_safe(
        str(ws_settings.get("transfer_destination_number") or "")
    )
    if transfer_number:
        candidates.append(transfer_number)

    workspace_id = getattr(workspace, "id", None)
    if workspace_id is not None:
        result = await db.execute(
            apply_workspace_scope(
                select(PhoneNumber.phone_number), PhoneNumber, workspace_id
            ).where(PhoneNumber.voice_enabled.is_(True))
        )
        for owned in result.scalars().all():
            normalized = normalize_phone_safe(owned)
            if normalized:
                candidates.append(normalized)

    if requested is None:
        if not candidates:
            raise RepNumberNotAllowedError(
                "No callback number configured. Add a phone number to your profile "
                "or set a workspace transfer destination."
            )
        return candidates[0]

    normalized_request = normalize_phone_safe(requested)
    if not normalized_request:
        raise RepNumberNotAllowedError(f"'{requested}' is not a valid phone number.")
    if normalized_request not in candidates:
        raise RepNumberNotAllowedError(
            "That callback number is not allowed. Use your profile phone number, "
            "the workspace transfer destination, or a workspace phone number."
        )
    return normalized_request


async def start_user_call(
    *,
    db: AsyncSession,
    voice_service: TelnyxVoiceService,
    workspace_id: uuid.UUID,
    user_id: Any,
    to_number: str,
    from_number: str,
    rep_number: str,
    contact_phone: str | None,
    connection_id: str | None,
    webhook_url: str,
) -> Message:
    """Ring the rep first, then let the webhook handler dial and bridge the contact.

    Creates the call's ``Message`` row up front (``is_ai=False``) and dials only
    the rep leg. The contact is dialed by
    ``_handle_user_call_leg_answered`` once the rep actually picks up, so we
    never ring a customer into silence.

    Args:
        db: Database session.
        voice_service: Telnyx voice service (caller owns closing it).
        workspace_id: Workspace the call belongs to.
        user_id: The operator placing the call.
        to_number: The contact's number (leg B destination).
        from_number: Workspace caller ID presented on both legs.
        rep_number: Allowlisted number that rings the operator (leg A).
        contact_phone: Contact number used for conversation linking.
        connection_id: Telnyx connection ID, auto-discovered when None.
        webhook_url: Voice webhook URL so both legs report back to us.

    Returns:
        The call's ``Message`` row — ringing on success, failed if the rep leg
        could not be dialed.
    """
    to_number = voice_service.normalize_e164(to_number)
    from_number = voice_service.normalize_e164(from_number)
    rep_number = voice_service.normalize_e164(rep_number)

    log = logger.bind(service="user_call", to=to_number, from_=from_number)

    if not connection_id:
        try:
            connection_id = await voice_service.get_call_control_application_id(webhook_url)
        except ValueError as exc:
            log.error("user_call_connection_lookup_failed", error=str(exc))
            raise VoiceProviderUnavailableError(
                "Voice calling is not configured with Telnyx yet."
            ) from exc

    conversation = await voice_service.get_or_create_voice_conversation(
        db=db,
        workspace_phone=from_number,
        contact_phone=contact_phone or to_number,
        workspace_id=workspace_id,
    )

    message = Message(
        conversation_id=conversation.id,
        direction="outbound",
        channel="voice",
        body="",  # Voice calls don't have body text
        status=MessageStatus.QUEUED,
        is_ai=False,
    )
    db.add(message)
    await db.flush()

    rep_ccid = await voice_service.dial_transfer_leg(
        to_number=rep_number,
        from_number=from_number,
        connection_id=connection_id,
        webhook_url=webhook_url,
        client_state=make_user_call_leg_client_state(message.id),
        timeout_secs=REP_LEG_TIMEOUT_SECONDS,
    )

    conversation.channel = "voice"
    conversation.last_message_preview = "Voice call"
    conversation.last_message_at = datetime.now(UTC)

    if not rep_ccid:
        message.status = MessageStatus.FAILED
        message.error_code = "USER_CALL_REP_DIAL_FAILED"
        message.error_message = "Could not ring your phone."
        await db.commit()
        await db.refresh(message)
        log.error("user_call_rep_dial_failed", message_id=str(message.id))
        return message

    # The Message tracks the rep leg until the contact leg exists, so an
    # operator-initiated hangup and Telnyx's own hangup webhook both resolve
    # to this row while the rep's phone is still ringing.
    message.provider_message_id = rep_ccid
    message.status = MessageStatus.RINGING
    await db.commit()
    await db.refresh(message)

    await store_pending_user_call(
        PendingUserCall(
            rep_call_control_id=rep_ccid,
            contact_call_control_id=None,
            message_id=str(message.id),
            workspace_id=str(workspace_id),
            user_id=str(user_id),
            contact_number=to_number,
            from_number=from_number,
            stage=STAGE_DIALING_REP,
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    observe_voice_call_started(workspace_id)
    log.info(
        "user_call_rep_leg_dialed",
        message_id=str(message.id),
        rep_call_control_id=rep_ccid,
    )
    return message
